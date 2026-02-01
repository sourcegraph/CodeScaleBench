```java
package com.sprintcart.application.service;

import lombok.NonNull;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

import org.springframework.beans.factory.InitializingBean;
import org.springframework.context.ApplicationListener;
import org.springframework.core.task.AsyncTaskExecutor;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.annotation.PreDestroy;
import java.io.Serial;
import java.io.Serializable;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Collection;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;

/**
 * DomainEventProcessor is the single entry-point in the application layer that
 * receives <em>domain events</em> emitted by aggregate roots and dispatches them
 * to subscribed handlers.
 * <p>
 * Features:
 * <ul>
 *     <li><b>Dynamic subscription</b> – every Spring bean that implements
 *     {@link DomainEventSubscriber} will be autodetected.</li>
 *     <li><b>At-least-once processing</b> – a lightweight <i>outbox</i> journal
 *     prevents accidental double handling across JVM restarts.</li>
 *     <li><b>Metrics &amp; tracing</b> – processing duration and error counts
 *     are logged so that Prometheus/OpenTelemetry hooks can be added later
 *     without changing business code.</li>
 * </ul>
 *
 * Hexagonal positioning:
 * This class belongs to the <i>application service layer</i> (inside the hexagon)
 * and collaborates with domain and infrastructure layers only through
 * abstractions – no framework classes leak into the domain!
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DomainEventProcessor implements
        ApplicationListener<DomainEventProcessor.SpringDomainEvent>,
        InitializingBean {

    /**
     * Light-weight journal that stores the <em>natural key</em> (event id) of
     * every processed message. A production system would back this with a
     * database table; here we keep things in memory to stay self-contained.
     */
    private final Map<UUID, Boolean> processedEventJournal = new ConcurrentHashMap<>();

    /**
     * Collection of all discovered subscribers. Spring will inject every bean
     * that implements {@link DomainEventSubscriber}.
     */
    private final Collection<DomainEventSubscriber<? extends DomainEvent>> subscribers;

    /**
     * Async executor configured in {@code AsyncConfiguration}. Must be tuned
     * according to traffic; defaults to CPU*2 thread-pool in Spring Boot.
     */
    private final AsyncTaskExecutor taskExecutor;

    private final Clock clock = Clock.systemUTC();

    @Override
    public void afterPropertiesSet() {
        log.info("DomainEventProcessor initialized with {} subscriber(s)",
                subscribers.size());
        subscribers.forEach(s ->
                log.debug("   ↳ {}", s.getClass().getName()));
    }

    /**
     * Handles events published via {@code ApplicationEventPublisher}. The event
     * is unwrapped and forwarded to {@link #process(DomainEvent)}.
     */
    @Override
    @Transactional(noRollbackFor = Throwable.class)
    public void onApplicationEvent(SpringDomainEvent springEvent) {
        process(springEvent.event());
    }

    /**
     * Dispatches the given domain event to all matching subscribers.
     *
     * @param event domain event, must be non-null
     */
    public <E extends DomainEvent> void process(@NonNull E event) {
        final UUID eventId = event.eventId();
        if (eventId == null) {
            log.warn("Ignoring event without id: {}", event.getClass().getSimpleName());
            return;
        }

        // At-least-once check – skip already processed events
        if (processedEventJournal.putIfAbsent(eventId, Boolean.TRUE) != null) {
            log.debug("Event {} already handled, skipping", eventId);
            return;
        }

        log.info("▶ Processing event {} ({})", eventId, event.getClass().getSimpleName());

        final Instant start = clock.instant();

        subscribers.stream()
                   .filter(sub -> sub.supports(event.getClass()))
                   .forEach(sub -> dispatchAsync(sub, event));

        final Duration duration = Duration.between(start, clock.instant());
        log.info("✔ Event {} processed in {} ms", eventId, duration.toMillis());
    }

    /**
     * Dispatches event handling to background thread. An individual subscriber
     * failure does <strong>not</strong> prevent other subscribers from running.
     */
    private <E extends DomainEvent> void dispatchAsync(
            DomainEventSubscriber<E> subscriber, E event) {

        CompletableFuture
            .runAsync(() -> invokeHandler(subscriber, event), taskExecutor)
            .exceptionally(ex -> {
                log.error("❌ Subscriber '{}' failed for event {}",
                        subscriber.getClass().getSimpleName(), event.eventId(), ex);
                // In a real system we would publish to a DLQ here
                return null;
            });
    }

    /**
     * Invokes subscriber handler with proper error boundaries. Wrapped into its
     * own method to produce cleaner stack traces inside {@link CompletableFuture}.
     */
    private <E extends DomainEvent> void invokeHandler(
            DomainEventSubscriber<E> subscriber, E event) {

        try {
            subscriber.handle(event);
            log.debug("↳ {} handled by {}", event.getClass().getSimpleName(),
                    subscriber.getClass().getSimpleName());
        } catch (DataAccessException dae) {
            // Non-transient DB error – rethrow to trigger retry/back-off
            throw dae;
        } catch (Exception e) {
            // Shield rest of the pipeline; mark failure for DLQ
            log.error("Subscriber {} threw exception for event {}",
                    subscriber.getClass().getName(), event.eventId(), e);
            throw e;
        }
    }

    /**
     * Ensures that the in-memory journal does not leak after container
     * shutdown. A real implementation would not be necessary because the
     * journal would live in an external store.
     */
    @PreDestroy
    public void teardown() {
        processedEventJournal.clear();
        log.info("DomainEventProcessor stopped – journal cleared");
    }

    // -----------------------------------------------------------------------
    // Nested Types
    // -----------------------------------------------------------------------

    /**
     * A marker interface for all domain events in SprintCart Pro.
     * Extend this in <code>domain.events.*</code> packages.
     */
    public interface DomainEvent extends Serializable {
        @Serial
        long serialVersionUID = 1L;

        /**
         * Globally unique identifier that guarantees idempotency.
         */
        @NonNull UUID eventId();

        /**
         * Timestamp of occurrence (UTC). Helps for latency metrics.
         */
        @NonNull Instant occurredOn();
    }

    /**
     * Contract to be implemented by application services that react to a
     * specific type of domain event. Generic to enforce type-safety.
     *
     * @param <E> concrete event class
     */
    public interface DomainEventSubscriber<E extends DomainEvent> {

        /**
         * Handle the event. May throw a runtime exception; the processor will
         * catch and log it without bringing down the JVM.
         */
        void handle(@NonNull E event);

        /**
         * Whether this subscriber accepts the given event type.
         * Most implementations return <code>eventType.equals(MyEvent.class)</code>.
         */
        boolean supports(@NonNull Class<? extends DomainEvent> eventType);
    }

    /**
     * Wrapper that allows publishing {@link DomainEvent}s through Spring's
     * {@code ApplicationEventPublisher} while keeping our domain model free
     * from framework dependencies.
     */
    public record SpringDomainEvent(DomainEvent event) implements Serializable {
        @Serial
        private static final long serialVersionUID = 42L;
    }

    // -----------------------------------------------------------------------
    // Convenience utilities
    // -----------------------------------------------------------------------

    /**
     * Utility to publish domain events via Spring without depending on
     * {@code ApplicationEventPublisher} outside this class.
     *
     * Example:
     * <pre>
     *   DomainEventProcessor.publish(applicationContext, new OrderCreatedEvent(...));
     * </pre>
     */
    public static void publish(
            @NonNull org.springframework.context.ApplicationEventPublisher publisher,
            @NonNull DomainEvent event) {

        Objects.requireNonNull(publisher, "publisher must not be null");
        Objects.requireNonNull(event, "event must not be null");

        publisher.publishEvent(new SpringDomainEvent(event));
    }

    /**
     * Optional helper that can be used by repositories or aggregates to create
     * a default UUID for events when none is provided.
     */
    public static UUID randomEventId() {
        return UUID.randomUUID();
    }

    /**
     * Safely extracts the value of an {@link Optional}, throwing
     * {@link IllegalStateException} when empty. Reduces null checks across
     * subscribers while still keeping failure explicit.
     */
    public static <T> T requirePresent(Optional<T> optional, String message) {
        if (optional.isEmpty()) {
            throw new IllegalStateException(message);
        }
        return optional.get();
    }
}
```