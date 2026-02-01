```java
package com.opsforge.nexus.fileconverter.adapter.in.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.opsforge.nexus.fileconverter.application.port.in.FileConversionUseCase;
import com.opsforge.nexus.fileconverter.domain.ConversionJobId;
import com.opsforge.nexus.fileconverter.domain.FileConversionResult;
import com.opsforge.nexus.fileconverter.domain.enums.FileFormat;
import org.apache.commons.io.IOUtils;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.web.servlet.MockMvc;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;

import static org.hamcrest.MatcherAssert.assertThat;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.equalTo;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.http.HttpHeaders.CACHE_CONTROL;
import static org.springframework.http.HttpHeaders.CONTENT_DISPOSITION;
import static org.springframework.http.HttpHeaders.CONTENT_TYPE;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * Integration-style MVC test for {@link FileConversionController}.  The Web layer is loaded
 * with mocked {@link FileConversionUseCase} so the test remains fast and focused on
 * HTTP contract/business rules.
 */
@WebMvcTest(controllers = FileConversionController.class)
class FileConversionControllerTest {

    private static final String API_VERSION = "1.0";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private FileConversionUseCase conversionUseCase;

    @Nested
    @DisplayName("POST /v{version}/convert")
    class ConvertEndpoint {

        @Test
        @DisplayName("should accept multipart file, convert it, and stream binary response")
        void shouldConvertFileAndReturnConvertedContent() throws Exception {
            // given
            final byte[] raw = "dummy csv content".getBytes(StandardCharsets.UTF_8);
            final MockMultipartFile multipartFile =
                    new MockMultipartFile("file",
                                          "sample.csv",
                                          MediaType.TEXT_PLAIN_VALUE,
                                          raw);

            final byte[] convertedPdf = new ClassPathResource("files/sample.pdf").getInputStream().readAllBytes();
            final ConversionJobId jobId = new ConversionJobId(UUID.randomUUID());
            final FileConversionResult result = FileConversionResult.success(jobId, FileFormat.CSV, FileFormat.PDF, convertedPdf);

            when(conversionUseCase.convert(ArgumentMatchers.any()))
                    .thenReturn(result);

            // when / then
            mockMvc.perform(
                    multipart("/v" + API_VERSION + "/convert")
                            .file(multipartFile)
                            .param("targetFormat", "PDF")
                            .header("X-Client-Id", "gateway-test")
                            .characterEncoding("UTF-8"))
                   .andExpect(status().isOk())
                   .andExpect(header().string(CONTENT_TYPE, equalTo(MediaType.APPLICATION_PDF_VALUE)))
                   .andExpect(header().string(CONTENT_DISPOSITION, containsString("attachment; filename=\"sample.pdf\"")))
                   .andExpect(header().string(CACHE_CONTROL, "max-age=" + Duration.ofHours(24).getSeconds() + ", public"))
                   .andExpect(content().bytes(convertedPdf));
        }

        @Test
        @DisplayName("should return 400 BAD_REQUEST for unsupported target format")
        void shouldReturnBadRequestForUnsupportedTargetFormat() throws Exception {
            // given
            final byte[] raw = "irrelevant".getBytes(StandardCharsets.UTF_8);
            final MockMultipartFile multipartFile =
                    new MockMultipartFile("file",
                                          "payload.unknown",
                                          MediaType.APPLICATION_OCTET_STREAM_VALUE,
                                          raw);

            when(conversionUseCase.convert(any()))
                    .thenThrow(new IllegalArgumentException("Unsupported target format: XLS"));

            // when / then
            mockMvc.perform(
                    multipart("/v" + API_VERSION + "/convert")
                            .file(multipartFile)
                            .param("targetFormat", "XLS"))
                   .andExpect(status().isBadRequest())
                   .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                   .andExpect(jsonPath("$.title").value("Unsupported target format"))
                   .andExpect(jsonPath("$.detail").value("Unsupported target format: XLS"));
        }

        @Test
        @DisplayName("should return 422 UNPROCESSABLE_ENTITY when file part is missing")
        void shouldHandleMissingFileUpload() throws Exception {
            mockMvc.perform(
                    multipart("/v" + API_VERSION + "/convert")
                            .param("targetFormat", "PDF"))
                   .andExpect(status().isUnprocessableEntity())
                   .andExpect(content().contentType(MediaType.APPLICATION_PROBLEM_JSON))
                   .andExpect(jsonPath("$.title").value("File part is missing"));
        }
    }

    @Test
    @DisplayName("should propagate versioning information through 'X-Api-Version' header")
    void shouldRespectVersioningHeader() throws Exception {
        // given
        final byte[] rawData = IOUtils.toByteArray(new ClassPathResource("files/sample.csv"));
        final MockMultipartFile multipartFile =
                new MockMultipartFile("file",
                                      "sample.csv",
                                      MediaType.TEXT_PLAIN_VALUE,
                                      rawData);

        final FileConversionResult stubbedResult =
                FileConversionResult.success(new ConversionJobId(UUID.randomUUID()),
                                             FileFormat.CSV,
                                             FileFormat.JSON,
                                             "{\"dummy\":true}".getBytes(StandardCharsets.UTF_8));

        when(conversionUseCase.convert(any()))
                .thenReturn(stubbedResult);

        // when
        final String apiVersion = "2023-11";
        mockMvc.perform(
                multipart("/v" + API_VERSION + "/convert")
                        .file(multipartFile)
                        .param("targetFormat", "JSON")
                        .header("X-Api-Version", apiVersion))
               .andExpect(status().isOk())
               .andExpect(header().string("X-Api-Version", apiVersion))
               .andExpect(result -> assertThat(
                       "Controller must echo back version header for gateway routing",
                       result.getResponse().getHeader("X-Api-Version"),
                       equalTo(apiVersion)));
    }
}
```