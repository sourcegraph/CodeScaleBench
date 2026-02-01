package com.commercesphere.enterprise.config;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.function.Consumer;

import org.springdoc.core.customizers.OpenApiCustomiser;
import org.springdoc.core.customizers.OperationCustomizer;
import org.springdoc.core.GroupedOpenApi;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.info.BuildProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.util.StringUtils;

import io.swagger.v3.oas.models.Components;
import io.swagger.v3.oas.models.ExternalDocumentation;
import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.Operation;
import io.swagger.v3.oas.models.info.Contact;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.info.License;
import io.swagger.v3.oas.models.servers.Server;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.parameters.HeaderParameter;
import io.swagger.v3.oas.models.responses.ApiResponse;

/**
 * OpenAPI / Swagger configuration for CommerceSphere Enterprise Suite.
 *
 * <p>
 * Centralizes metadata, security schemes, built version information, and any
 * global operation customizations (headers, error responses, etc.).
 * </p>
 *
 * <p>
 * The configuration intentionally keeps a narrow surface area—client-facing
 * descriptions and documented behavior only—while internal implementation
 * details stay within service modules.  All beans here are singleton; each is
 * auto-detected by springdoc-openapi at runtime.
 * </p>
 *
 * @author  CommerceSphere
 */
@Configuration
public class OpenApiConfig {

    /**
     * Header used for distributed tracing and audit logging. Added to every
     * generated operation so API consumers can easily correlate requests.
     */
    private static final String HEADER_REQUEST_ID = "X-Request-Id";

    /**
     * Name of the security scheme as referenced by {@link SecurityRequirement}.
     */
    private static final String SECURITY_SCHEME_BEARER = "bearer-jwt";

    @Value("${commerce.api.base-path:/api}")
    private String apiBasePath;

    @Value("${springdoc.swagger-ui.server-url:}")
    private String swaggerServerUrl;

    @Autowired(required = false)
    private BuildProperties buildProperties;

    /* ---------------------------------------------------------------------- */
    /* Public Bean Definitions                                                */
    /* ---------------------------------------------------------------------- */

    /**
     * Main {@link OpenAPI} bean containing documentation metadata and reusable
     * components.
     */
    @Bean
    public OpenAPI commerceSphereOpenApi() {

        Info info = new Info()
                .title("CommerceSphere Enterprise Suite API")
                .description("""
                        Unified e-commerce platform exposing contract-driven product, pricing,
                        and order endpoints.  All APIs are protected with OAuth2 bearer tokens.
                        """)
                .version(resolveBuildVersion())
                .contact(new Contact()
                        .name("CommerceSphere Support")
                        .email("support@commercesphere.com")
                        .url("https://docs.commercesphere.com"))
                .license(new License()
                        .name("Commercial License")
                        .url("https://www.commercesphere.com/legal/license"));

        Components components = new Components()
                .addSecuritySchemes(SECURITY_SCHEME_BEARER, jwtSecurityScheme());

        ExternalDocumentation externalDocs = new ExternalDocumentation()
                .description("CommerceSphere Developer Portal")
                .url("https://developers.commercesphere.com");

        OpenAPI openApi = new OpenAPI()
                .info(info)
                .components(components)
                .externalDocs(externalDocs)
                .addSecurityItem(new SecurityRequirement().addList(SECURITY_SCHEME_BEARER))
                .servers(resolveServers());

        return openApi;
    }

    /**
     * Groups all REST controllers under a single logical grouping. In large
     * deployments, multiple groups can be introduced (e.g., "admin", "public").
     */
    @Bean
    public GroupedOpenApi commerceSphereGroupedOpenApi(OperationCustomizer headerCustomizer,
                                                       OpenApiCustomiser globalResponseCustomizer) {
        return GroupedOpenApi.builder()
                .group("commercesphere-ent-suite")
                .pathsToMatch(String.format("%s/**", apiBasePath))
                .addOperationCustomizer(headerCustomizer)
                .addOpenApiCustomiser(globalResponseCustomizer)
                .build();
    }

    /**
     * Adds the {@code X-Request-Id} header parameter to all API operations
     * enabling easy request tracing.
     */
    @Bean
    public OperationCustomizer headerCustomizer() {
        return (Operation operation, org.springframework.core.MethodParameter methodParameter) -> {
            HeaderParameter requestIdHeader = new HeaderParameter()
                    .name(HEADER_REQUEST_ID)
                    .description("Correlation identifier propagated for distributed tracing.")
                    .required(false)
                    .example("0af7651916cd43dd8448eb211c80319c");
            operation.addParametersItem(requestIdHeader);
            return operation;
        };
    }

    /**
     * Adds standardized error responses ({@code 400} & {@code 500}) to every
     * operation, ensuring consistent documentation without boilerplate
     * annotations on each controller method.
     */
    @Bean
    public OpenApiCustomiser globalResponseCustomizer() {
        ApiResponse badRequest = new ApiResponse()
                .description("Bad Request — validation failed or malformed data.");
        ApiResponse internalError = new ApiResponse()
                .description("Internal Server Error — unexpected condition encountered.");

        return openApi -> Optional.ofNullable(openApi.getPaths()).ifPresent(paths ->
                paths.values().forEach(pathItem ->
                        pathItem.readOperations().forEach(augmentWithGlobalResponses(badRequest, internalError)))
        );
    }

    /* ---------------------------------------------------------------------- */
    /* Private Helpers                                                        */
    /* ---------------------------------------------------------------------- */

    /**
     * Factory method for JWT security scheme.
     */
    private SecurityScheme jwtSecurityScheme() {
        return new SecurityScheme()
                .name(SECURITY_SCHEME_BEARER)
                .type(SecurityScheme.Type.HTTP)
                .scheme("bearer")
                .bearerFormat("JWT")
                .description("OAuth2 Bearer token obtained from the /oauth/token endpoint.");
    }

    /**
     * Attempts to read build metadata; falls back to a runtime timestamp when
     * unavailable (e.g., during tests).
     */
    private String resolveBuildVersion() {
        try {
            if (buildProperties != null && StringUtils.hasText(buildProperties.getVersion())) {
                return buildProperties.getVersion();
            }
        } catch (Exception ignore) {
            // Safe fallback (should never break startup).
        }
        return "snapshot-" + OffsetDateTime.now();
    }

    /**
     * Builds the {@link Server} list. If a custom URL is provided for Swagger
     * we register that; otherwise, we rely on SpringDoc to infer the current
     * request's base URL.
     */
    private List<Server> resolveServers() {
        if (StringUtils.hasText(swaggerServerUrl)) {
            Server server = new Server()
                    .url(swaggerServerUrl)
                    .description("Resolved server URL injected via configuration.");
            return List.of(server);
        }
        return List.of(); // Allow swagger-ui to use the current origin.
    }

    /**
     * Utility that returns a {@link Consumer} augmenting an {@link Operation}
     * with global responses.
     */
    private Consumer<Operation> augmentWithGlobalResponses(ApiResponse badRequest,
                                                           ApiResponse internalError) {
        return operation -> operation.getResponses()
                .addApiResponse("400", badRequest)
                .addApiResponse("500", internalError);
    }
}