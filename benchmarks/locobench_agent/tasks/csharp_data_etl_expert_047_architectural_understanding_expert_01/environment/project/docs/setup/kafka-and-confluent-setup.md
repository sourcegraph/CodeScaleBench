using System;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Confluent.Kafka;
using DotNet.Testcontainers.Builders;
using DotNet.Testcontainers.Configurations;
using DotNet.Testcontainers.Containers;
using Xunit;

namespace PaletteStream.ETL.Canvas.Tests.Setup
{
    /// <summary>
    /// Integration‐tests the local Kafka & Confluent stack used by PaletteStream ETL Canvas.
    /// 
    /// The tests spin-up disposable Kafka and Schema-Registry containers (via Testcontainers),
    /// create a topic, publish a test message, and verify that it can be consumed within a
    /// configurable timeout.  This provides early feedback that the developer workstation
    /// or CI agent can run Kafka-backed, streaming ETL pipelines before heavier test suites
    /// execute.
    /// </summary>
    public sealed class KafkaAndConfluentSetupTests : IAsyncLifetime
    {
        private const string TopicName         = "palette.pipeline.test-topic";
        private const string TestMessageKey    = "ping";
        private const string TestMessageValue  = "🎨 palette-stream pong!";

        private readonly KafkaTestcontainer _kafkaContainer;

        public KafkaAndConfluentSetupTests()
        {
            _kafkaContainer = new TestcontainersBuilder<KafkaTestcontainer>()
                .WithKafka(new KafkaTestcontainerConfiguration
                {
                    //   NOTE: The Confluent community image ships with a Schema-Registry bundled
                    //         image, but we use the lightweight testcontainers Module here.
                    //
                    //         If you need Schema-Registry, simply chain a second container:
                    //            .WithImage("confluentinc/cp-schema-registry:7.4.0")
                    //            .WithPortBinding(8081, true)
                    //
                    //         …and set KAFKA_ADVERTISED_LISTENERS accordingly.
                    //
                    KafkaImage           = "confluentinc/cp-kafka:7.4.0",
                    AllowTopicCreation   = true,
                    CleanUp              = true,
                    WaitTimeout          = TimeSpan.FromMinutes(2)
                })
                .WithName($"palette-kafka-integration-{Guid.NewGuid():N}")
                .Build();
        }

        #region IAsyncLifetime

        public async Task InitializeAsync()
        {
            await _kafkaContainer.StartAsync();

            // Create the topic ahead of time to reduce test flakiness (Kafka auto-create
            // can be disabled in production clusters).
            var adminConfig = new AdminClientConfig { BootstrapServers = _kafkaContainer.BootstrapServers };
            using var adminClient = new AdminClientBuilder(adminConfig).Build();
            try
            {
                await adminClient.CreateTopicsAsync(new[]
                {
                    new TopicSpecification
                    {
                        Name              = TopicName,
                        NumPartitions     = 1,
                        ReplicationFactor = 1
                    }
                });
            }
            catch (CreateTopicsException ex) when (ex.Results.TrueForAll(r => r.Error.IsError && r.Error.Code == ErrorCode.TopicAlreadyExists))
            {
                // Topic already exists – swallow and continue.
            }
        }

        public async Task DisposeAsync()
        {
            if (_kafkaContainer != null)
            {
                await _kafkaContainer.StopAsync();
            }
        }

        #endregion

        [Fact(DisplayName = "Kafka container should be reachable and echo messages")]
        public async Task KafkaContainer_ShouldEchoMessages()
        {
            var cts               = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            var bootstrapServers  = _kafkaContainer.BootstrapServers;

            // -------- Producer --------
            var producerConfig = new ProducerConfig
            {
                BootstrapServers = bootstrapServers,
                // Ensure delivery guarantees similar to production
                EnableIdempotence = true,
                Acks              = Acks.All
            };

            using var producer = new ProducerBuilder<string, string>(producerConfig).Build();
            var deliveryResult = await producer.ProduceAsync(
                TopicName,
                new Message<string, string>
                {
                    Key   = TestMessageKey,
                    Value = TestMessageValue
                },
                cts.Token);

            Assert.False(deliveryResult.Status == PersistenceStatus.NotPersisted,
                $"Message was not persisted to Kafka.  Status: {deliveryResult.Status}");

            // -------- Consumer --------
            var consumerConfig = new ConsumerConfig
            {
                BootstrapServers = bootstrapServers,
                GroupId          = $"palette-consumer-{Guid.NewGuid():N}",
                AutoOffsetReset  = AutoOffsetReset.Earliest,
                EnableAutoCommit = false
            };

            using var consumer = new ConsumerBuilder<string, string>(consumerConfig).Build();
            consumer.Subscribe(TopicName);

            var consumeResult = consumer.Consume(cts.Token); // will block until message is available or CTS expires

            Assert.NotNull(consumeResult);
            Assert.Equal(TestMessageKey,   consumeResult.Message.Key);
            Assert.Equal(TestMessageValue, consumeResult.Message.Value);
        }
    }
}