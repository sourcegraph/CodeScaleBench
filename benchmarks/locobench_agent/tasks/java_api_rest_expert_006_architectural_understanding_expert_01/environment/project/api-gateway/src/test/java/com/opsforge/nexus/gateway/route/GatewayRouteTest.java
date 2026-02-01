```java
package com.opsforge.nexus.gateway.route;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.equalTo;
import static com.github.tomakehurst.wiremock.client.WireMock.get;
import static com.github.tomakehurst.wiremock.client.WireMock.urlPathMatching;
import static org.assertj.core.api.Assertions.assertThat;

import com.github.tomakehurst.wiremock.WireMockServer;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.util.TestPropertyValues;
import org.springframework.boot.web.reactive.context.ReactiveWebServerApplicationContext;
import org.springframework.cloud.gateway.route.RouteDefinition;
import org.springframework.cloud.gateway.route.RouteDefinitionLocator;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.reactive.server.WebTestClient;

/**
 * GatewayRouteTest spins up a real SpringBoot web environment and a WireMock stub that stands in
 * for a downstream micro-service. The suite validates:
 *
 * <ul>
 *   <li>Route definitions are loaded and discoverable via {@link RouteDefinitionLocator}
 *   <li>Requests are forwarded to the correct downstream service
 *   <li>Important headers (trace-ids, versions, etc.) are propagated
 *   <li>Error handling & fallbacks when the downstream service is unavailable
 * </ul>
 *
 * <p>The tests intentionally use very small timeouts to fail fast if the Gateway blocks.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ActiveProfiles("test")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
class GatewayRouteTest {

  private static final Logger log = LoggerFactory.getLogger(GatewayRouteTest.class);

  /** Reusable header names that the platform cares about. */
  private static final String HEADER_TRACE_ID = "X-Trace-Id";
  private static final String HEADER_API_VERSION = "X-API-Version";

  /** Stub server that represents the downstream “File Conversion” micro-service. */
  private static final WireMockServer wireMockServer = new WireMockServer(0); // auto-select port

  @Autowired private WebTestClient webTestClient;

  @Autowired private RouteDefinitionLocator routeLocator;

  /**
   * Registers dynamic Spring properties <strong>before</strong> the ApplicationContext is
   * refreshed. We inject the WireMock port into the Gateway's yaml-based route configuration via
   * placeholder replacement (see <code>${utility-file-conversion.port}</code> in application.yml).
   */
  @DynamicPropertySource
  static void overrideProperties(DynamicPropertyRegistry registry) {
    registry.add("utility-file-conversion.port", wireMockServer::port);
  }

  /** Boot WireMock once for the entire test class. */
  @BeforeAll
  static void startStub() {
    wireMockServer.start();

    // Happy-path stub
    wireMockServer.stubFor(
        get(urlPathMatching("/internal/file-conversion/pdf2doc"))
            .withQueryParam("inputFormat", equalTo("pdf"))
            .withQueryParam("outputFormat", equalTo("doc"))
            .willReturn(
                aResponse()
                    .withStatus(200)
                    .withHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                    .withHeader(HEADER_TRACE_ID, "downstream-trace")
                    .withBody(
                        """
                        {
                          "status": "SUCCESS",
                          "jobId": "job-123456"
                        }
                        """)));

    // Error-path stub
    wireMockServer.stubFor(
        get(urlPathMatching("/internal/file-conversion/trigger-error"))
            .willReturn(
                aResponse()
                    .withStatus(500)
                    .withHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                    .withBody(
                        """
                        {
                          "errorCode": "CONVERSION_ENGINE_FAILURE",
                          "message": "Unable to process request"
                        }
                        """)));
  }

  @AfterAll
  static void stopStub() {
    wireMockServer.stop();
  }

  // -----------------------------------------------------------------------
  // Test cases
  // -----------------------------------------------------------------------

  @Test
  @Order(1)
  @DisplayName("Gateway should load and expose the expected route definitions")
  void routeDefinitionsAreDiscovered() {
    List<RouteDefinition> routes =
        routeLocator.getRouteDefinitions().collectList().block(Duration.ofSeconds(2));

    assertThat(routes)
        .isNotNull()
        .anyMatch(
            route ->
                Objects.equals(route.getId(), "file-conversion-service")
                    && route.getPredicates().stream()
                        .anyMatch(p -> p.getArgs().values().stream().anyMatch(v -> v.contains("/v1/utilities/convert/**"))));
  }

  @Test
  @Order(2)
  @DisplayName("Gateway forwards a happy-path request and preserves critical headers")
  void fileConversionRouteShouldForwardAndReturnResponse() {
    String traceId = "test-trace-123";

    webTestClient
        .get()
        .uri(
            uriBuilder ->
                uriBuilder
                    .path("/v1/utilities/convert/pdf2doc")
                    .queryParam("inputFormat", "pdf")
                    .queryParam("outputFormat", "doc")
                    .build())
        .header(HEADER_TRACE_ID, traceId)
        .header(HEADER_API_VERSION, "1")
        .accept(MediaType.APPLICATION_JSON)
        .exchange()
        .expectStatus()
        .isOk()
        .expectHeader()
        .valueEquals(HEADER_TRACE_ID, "downstream-trace") // overwritten by downstream
        .expectHeader()
        .contentTypeCompatibleWith(MediaType.APPLICATION_JSON)
        .expectBody()
        .jsonPath("$.status")
        .isEqualTo("SUCCESS")
        .jsonPath("$.jobId")
        .isEqualTo("job-123456");
  }

  @Test
  @Order(3)
  @DisplayName("Gateway should transform downstream errors into standardized problem-details")
  void gatewayTransformsDownstreamErrors() {
    webTestClient
        .get()
        .uri("/v1/utilities/convert/trigger-error")
        .accept(MediaType.APPLICATION_JSON)
        .exchange()
        .expectStatus()
        .is5xxServerError()
        .expectHeader()
        .contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON)
        .expectBody()
        .jsonPath("$.title")
        .isEqualTo("Utility Service Failure")
        .jsonPath("$.status")
        .isEqualTo(502) // Gateway Bad-Gateway
        .jsonPath("$.detail")
        .value(detail -> assertThat(detail).contains("CONVERSION_ENGINE_FAILURE"));
  }
}
```