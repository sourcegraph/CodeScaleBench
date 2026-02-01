```cpp
/************************************************************************************
 *  File: cardio_insight_360/tests/unit/test_hl7_parser.cpp
 *  Project: CardioInsight360 – Unified Healthcare Analytics Engine
 *
 *  Purpose:
 *      Unit-tests for the HL7 v2.x parser responsible for ingesting and normalising
 *      HL7 messages prior to dispatching them onto the internal event-streaming bus.
 *
 *  Test-Suite Highlights:
 *      • End-to-end round-trip parsing of an ADT^A01 (Patient Admit) message
 *      • Parsing and semantic validation of an ORU^R01 (Observation) message
 *      • Robustness checks for malformed or incomplete messages
 *      • Thread-safety verification under high-volume, parallel invocations
 *      • Custom GoogleMock matcher to improve assertion readability
 *
 *  Dependencies:
 *      • GoogleTest / GoogleMock
 *      • Production headers: hl7_parser.hpp, hl7_message.hpp
 *
 *  Build:
 *      The CMakeLists.txt for the tests target links against gtest, gmock,
 *      and the “cardio_insight_360” static/shared library that contains the
 *      concrete Hl7Parser implementation under test.
 *
 ************************************************************************************/

#include <gmock/gmock.h>
#include <gtest/gtest.h>

#include <chrono>
#include <future>
#include <random>
#include <thread>
#include <vector>

// Production headers ----------------------------------------------------------
#include "hl7_parser/hl7_message.hpp"
#include "hl7_parser/hl7_parser.hpp"

// Namespaces used throughout the test-suite -----------------------------------
using namespace cardio_insight_360::hl7;     // Domain model + parser interfaces
using testing::AllOf;
using testing::Eq;
using testing::Field;
using testing::Matcher;
using testing::Property;
using testing::SizeIs;
using testing::StrEq;

/**************************************************************************************************
 * Helper utilities
 **************************************************************************************************/

namespace
{

// Returns a deterministic ADT^A01 message (patient admission).
std::string makeAdtA01() noexcept
{
    return
        "MSH|^~\\&|HIS|RIH|EKG|EKG|202406031020||ADT^A01|MSG00001|P|2.5\r"
        "EVN|A01|202406031020|||^KOCH^JANE\r"
        "PID|1||12345678^^^HOSP^MR||DOE^JOHN^^^^^L||19800515|M|| "
        "|123 Main St^^Metropolis^NY^10001||555-1234|||M|S||123456789|987-65-4320\r"
        "PV1|1|I|2000^2012^01||||004777^STONE^JULIE^A|||SUR||||ADM|A0|\r";
}

// Generates an ORU^R01 message that contains an SpO₂ observation.
std::string makeOruR01(double spo2Value = 97.5) noexcept
{
    std::ostringstream ss;
    ss << "MSH|^~\\&|MONITOR|ICU|CIS|CIS|202406031021||ORU^R01|MSG00002|P|2.5\r"
       << "PID|1||987654^^^HOSP^MR||SMITH^ALICE^^^^^L||19751225|F|||"
       << "456 Elm St^^Metropolis^NY^10001||555-6789\r"
       << "OBR|1||789012^MONITOR|15045^SpO2^LN|||202406031020|||||||||"
       << "^^^^^ICU||||||F\r"
       << "OBX|1|NM|15045^SpO2^LN||" << std::fixed << std::setprecision(1) << spo2Value
       << "|%|95-100|N|||F\r";
    return ss.str();
}

// Minimalistic random HL7 message generator for stress testing.
std::string makeRandomHl7(size_t seed) noexcept
{
    // Rotate among two templates; inject randomness in patient-id to mimic real data.
    if (seed % 2 == 0)
    {
        auto msg = makeAdtA01();
        // Replace medical-record number with pseudo-random value.
        auto pos = msg.find("12345678");
        if (pos != std::string::npos)
        {
            msg.replace(pos, 8, std::to_string(10000000 + (seed % 90000000)));
        }
        return msg;
    }
    return makeOruR01(94.0 + static_cast<double>(seed % 6));
}

// Custom matcher to compare HL7 field values inside the strongly-typed object.
MATCHER_P2(HasObservation, loincCode, numericValue,
           "Checks that HL7Message contains numeric observation " + std::string(loincCode))
{
    if (arg.messageType() != "ORU")
        return false;

    const auto& obxSegments = arg.observations();
    for (const auto& obx : obxSegments)
    {
        if (obx.code == loincCode && std::fabs(obx.numericValue - numericValue) < 1e-6)
            return true;
    }
    *result_listener << "expected LOINC " << loincCode << " not found";
    return false;
}

} // anonymous namespace

/**************************************************************************************************
 * Test fixture
 **************************************************************************************************/

class HL7ParserTest : public ::testing::Test
{
protected:
    Hl7Parser parser_;    // System under test

    void SetUp() override
    {
        // Parser may need contextual configuration (character set, validation profile, etc.).
        Hl7Parser::Settings settings;
        settings.defaultEncoding      = Hl7Parser::Encoding::UTF8;
        settings.schemaValidation     = true;
        settings.fieldEscapePolicy    = Hl7Parser::FieldEscapePolicy::Strict;
        parser_.configure(settings);
    }
};

/**************************************************************************************************
 * Test cases
 **************************************************************************************************/

TEST_F(HL7ParserTest, ParsesAdtA01Successfully)
{
    const auto raw = makeAdtA01();

    Hl7Message msg;
    ASSERT_NO_THROW(msg = parser_.parse(raw));

    // Header checks
    EXPECT_THAT(msg.sendingApplication(), StrEq("HIS"));
    EXPECT_THAT(msg.messageControlId(),   StrEq("MSG00001"));
    EXPECT_THAT(msg.messageType(),        StrEq("ADT"));
    EXPECT_THAT(msg.triggerEvent(),       StrEq("A01"));

    // PID segment checks
    const auto& pid = msg.patient();
    EXPECT_THAT(pid.medicalRecordNumber,  StrEq("12345678"));
    EXPECT_THAT(pid.lastName,             StrEq("DOE"));
    EXPECT_THAT(pid.firstName,            StrEq("JOHN"));
    EXPECT_THAT(pid.birthDate.toIsoString(), StrEq("1980-05-15"));
    EXPECT_EQ(pid.gender, Patient::Gender::Male);

    // PV1 segment checks
    const auto& pv1 = msg.visit();
    EXPECT_EQ(pv1.patientClass, Visit::PatientClass::Inpatient);
    EXPECT_THAT(pv1.attendingDoctor.lastName, StrEq("STONE"));
}

TEST_F(HL7ParserTest, ParsesOruR01AndExtractsObservation)
{
    constexpr double kExpectedSpO2 = 97.5;
    const auto raw = makeOruR01(kExpectedSpO2);

    const Hl7Message msg = parser_.parse(raw);

    EXPECT_THAT(msg, HasObservation("15045", kExpectedSpO2));
}

TEST_F(HL7ParserTest, ThrowsMeaningfulExceptionOnMalformedMessage)
{
    const std::string malformed = "MSH|^~\\&|BAD|MSG\rPID|||"; // Intentionally truncated

    try
    {
        const auto unused = parser_.parse(malformed);
        FAIL() << "Expected Hl7ParserError to be thrown";
    }
    catch (const Hl7ParserError& e)
    {
        // Error code must map to syntax-error and include offset > 0
        EXPECT_EQ(e.code(), Hl7ParserError::Code::SyntaxError);
        EXPECT_GT(e.byteOffset(), 0U);
        EXPECT_THAT(std::string{e.what()}, testing::HasSubstr("PID"));
    }
    catch (...)
    {
        FAIL() << "Unexpected exception type";
    }
}

TEST_F(HL7ParserTest, ParserIsThreadSafeUnderParallelLoad)
{
    constexpr std::size_t kNumThreads  = std::thread::hardware_concurrency();
    constexpr std::size_t kIterations  = 10'000;

    std::atomic<bool>     failed{false};
    std::vector<std::thread> workers;
    workers.reserve(kNumThreads);

    // Launch thread-pool
    for (std::size_t t = 0; t < kNumThreads; ++t)
    {
        workers.emplace_back([&, t]
        {
            for (std::size_t i = 0; i < kIterations && !failed.load(); ++i)
            {
                const auto raw = makeRandomHl7(i + t * kIterations);

                try
                {
                    const auto msg = parser_.parse(raw);
                    // Spot check invariant: messageControlId must not be empty.
                    if (msg.messageControlId().empty())
                    {
                        failed = true;
                        break;
                    }
                }
                catch (const std::exception& ex)
                {
                    failed = true;
                    ADD_FAILURE_AT(__FILE__, __LINE__)
                        << "Exception in thread " << t << ": " << ex.what();
                    break;
                }
            }
        });
    }

    for (auto& th : workers) th.join();

    EXPECT_FALSE(failed.load());
}

TEST_F(HL7ParserTest, RoundTripSerializationMaintainsSemanticIntegrity)
{
    const auto originalRaw = makeAdtA01();
    const auto parsed      = parser_.parse(originalRaw);
    const auto serialized  = parser_.serialize(parsed);

    // The serialized form may differ at segment/field formatting level; re-parse it and compare.
    const auto reparsed = parser_.parse(serialized);

    EXPECT_EQ(reparsed.messageType(),  parsed.messageType());
    EXPECT_EQ(reparsed.triggerEvent(), parsed.triggerEvent());

    // Ensure patient-level immutable identifiers remain identical.
    EXPECT_EQ(reparsed.patient().medicalRecordNumber,
              parsed.patient().medicalRecordNumber);
    EXPECT_EQ(reparsed.patient().nationalIdentifier,
              parsed.patient().nationalIdentifier);
}

/**************************************************************************************************
 * End of file
 **************************************************************************************************/
```