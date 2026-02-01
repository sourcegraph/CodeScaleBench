```java
package com.sprintcart.adapters.search.elasticsearch;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sprintcart.domain.search.ProductSearchDocument;
import com.sprintcart.domain.search.SearchException;
import com.sprintcart.domain.search.SearchPort;
import org.elasticsearch.action.DocWriteRequest;
import org.elasticsearch.action.bulk.BulkRequest;
import org.elasticsearch.action.bulk.BulkResponse;
import org.elasticsearch.action.delete.DeleteRequest;
import org.elasticsearch.action.index.IndexRequest;
import org.elasticsearch.action.search.SearchRequest;
import org.elasticsearch.action.search.SearchResponse;
import org.elasticsearch.action.support.WriteRequest;
import org.elasticsearch.client.RequestOptions;
import org.elasticsearch.client.RestHighLevelClient;
import org.elasticsearch.client.indices.CreateIndexRequest;
import org.elasticsearch.client.indices.GetIndexRequest;
import org.elasticsearch.common.xcontent.XContentType;
import org.elasticsearch.index.query.QueryBuilders;
import org.elasticsearch.rest.RestStatus;
import org.elasticsearch.search.SearchHit;
import org.elasticsearch.search.builder.SearchSourceBuilder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Repository;

import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * Elasticsearch implementation of the {@link SearchPort}.
 * <p>
 * The adapter is responsible for translating domain-level search
 * commands into Elasticsearch REST calls and mapping the results back
 * into domain objects.
 */
@Repository
public class ElasticsearchAdapter implements SearchPort {

    private static final Logger LOGGER = LoggerFactory.getLogger(ElasticsearchAdapter.class);

    private final RestHighLevelClient client;
    private final ObjectMapper objectMapper;
    private final String indexName;

    public ElasticsearchAdapter(
            RestHighLevelClient client,
            ObjectMapper objectMapper,
            @Value("${search.elasticsearch.index.product:products}") String indexName) {

        this.client = client;
        this.objectMapper = objectMapper;
        this.indexName = indexName;

        ensureIndexExists();
    }

    @Override
    public void index(@NonNull ProductSearchDocument document) {
        IndexRequest request = buildIndexRequest(document);
        try {
            client.index(request, RequestOptions.DEFAULT);
            LOGGER.debug("Indexed product {} into '{}'", document.getId(), indexName);
        } catch (IOException ex) {
            LOGGER.error("Unable to index product {} into '{}'", document.getId(), indexName, ex);
            throw new SearchException("Failed to index product " + document.getId(), ex);
        }
    }

    @Override
    public void bulkIndex(@NonNull List<ProductSearchDocument> documents) {
        if (documents.isEmpty()) {
            return;
        }
        BulkRequest bulkRequest = new BulkRequest();
        documents.stream()
                 .map(this::buildIndexRequest)
                 .forEach(bulkRequest::add);

        // Use WAIT_UNTIL to make sure the documents are searchable right after the call returns
        bulkRequest.setRefreshPolicy(WriteRequest.RefreshPolicy.WAIT_UNTIL);

        try {
            BulkResponse response = client.bulk(bulkRequest, RequestOptions.DEFAULT);
            if (response.hasFailures()) {
                LOGGER.warn("Bulk indexing finished with failures: {}", response.buildFailureMessage());
            } else if (LOGGER.isDebugEnabled()) {
                LOGGER.debug("Bulk indexed {} products into '{}'", documents.size(), indexName);
            }
        } catch (IOException ex) {
            LOGGER.error("Bulk indexing operation failed", ex);
            throw new SearchException("Bulk indexing failed", ex);
        }
    }

    @Override
    public Page<ProductSearchDocument> search(@NonNull String query, @NonNull Pageable pageable) {
        SearchRequest searchRequest = new SearchRequest(indexName);

        SearchSourceBuilder sourceBuilder = new SearchSourceBuilder()
                .query(QueryBuilders.multiMatchQuery(query, "name", "description", "categories", "brand"))
                .from((int) pageable.getOffset())
                .size(pageable.getPageSize())
                .trackTotalHits(true);

        searchRequest.source(sourceBuilder);

        try {
            SearchResponse response = client.search(searchRequest, RequestOptions.DEFAULT);

            if (response.status() != RestStatus.OK) {
                throw new SearchException("Elasticsearch responded with status " + response.status());
            }

            long totalHits = response.getHits().getTotalHits().value;

            List<ProductSearchDocument> results = Arrays.stream(response.getHits().getHits())
                    .map(this::hitToDocument)
                    .filter(Objects::nonNull)
                    .collect(Collectors.toList());

            return new PageImpl<>(results, pageable, totalHits);
        } catch (IOException ex) {
            LOGGER.error("Search operation failed for query '{}'", query, ex);
            throw new SearchException("Search operation failed", ex);
        }
    }

    @Override
    public void delete(@NonNull String id) {
        DeleteRequest deleteRequest = new DeleteRequest(indexName, id)
                .setRefreshPolicy(WriteRequest.RefreshPolicy.WAIT_UNTIL);
        try {
            client.delete(deleteRequest, RequestOptions.DEFAULT);
            LOGGER.debug("Deleted document {} from '{}'", id, indexName);
        } catch (IOException ex) {
            LOGGER.error("Unable to delete document {} from '{}'", id, indexName, ex);
            throw new SearchException("Failed to delete document " + id, ex);
        }
    }

    /* --------------------------------------------------------------------- */
    /* Private helpers                                                       */
    /* --------------------------------------------------------------------- */

    private IndexRequest buildIndexRequest(ProductSearchDocument document) {
        Map<String, Object> jsonMap = objectMapper.convertValue(
                document, new TypeReference<Map<String, Object>>() {});
        return new IndexRequest(indexName)
                .id(document.getId())
                .opType(DocWriteRequest.OpType.INDEX)
                .source(jsonMap)
                .setRefreshPolicy(WriteRequest.RefreshPolicy.WAIT_UNTIL);
    }

    private ProductSearchDocument hitToDocument(SearchHit hit) {
        try {
            ProductSearchDocument doc =
                    objectMapper.readValue(hit.getSourceAsString(), ProductSearchDocument.class);
            doc.setId(hit.getId()); // preserve ES-generated ID when necessary
            return doc;
        } catch (IOException ex) {
            LOGGER.warn("Failed to deserialize search hit {}", hit.getId(), ex);
            return null;
        }
    }

    /**
     * Ensures that the configured index exists and, if not, creates it.
     *
     * Index creation is idempotent; if the index is already present the call is a no-op.
     */
    private void ensureIndexExists() {
        try {
            GetIndexRequest getIndexRequest = new GetIndexRequest(indexName);
            boolean exists = client.indices().exists(getIndexRequest, RequestOptions.DEFAULT);

            if (!exists) {
                LOGGER.info("Index '{}' not found, creating it …", indexName);
                CreateIndexRequest createIndexRequest = new CreateIndexRequest(indexName);
                createIndexRequest.mapping(defaultMappings(), XContentType.JSON);
                client.indices().create(createIndexRequest, RequestOptions.DEFAULT);
            }
        } catch (IOException ex) {
            LOGGER.error("Failed to verify or create index '{}'", indexName, ex);
            throw new IllegalStateException("Elasticsearch index initialization failed", ex);
        }
    }

    /**
     * A very small, opinionated mapping suited for {@link ProductSearchDocument}.
     * In real life this would be placed in its own JSON file or loaded dynamically.
     */
    private String defaultMappings() {
        // language=json
        return "{\n" +
               "  \"properties\": {\n" +
               "    \"name\":        {\"type\": \"text\", \"analyzer\": \"standard\"},\n" +
               "    \"description\": {\"type\": \"text\", \"analyzer\": \"standard\"},\n" +
               "    \"price\":       {\"type\": \"double\"},\n" +
               "    \"categories\":  {\"type\": \"keyword\"},\n" +
               "    \"brand\":       {\"type\": \"keyword\"},\n" +
               "    \"inventory\":   {\"type\": \"integer\"},\n" +
               "    \"createdAt\":   {\"type\": \"date\", \"format\": \"strict_date_optional_time||epoch_millis\"}\n" +
               "  }\n" +
               "}";
    }
}
```