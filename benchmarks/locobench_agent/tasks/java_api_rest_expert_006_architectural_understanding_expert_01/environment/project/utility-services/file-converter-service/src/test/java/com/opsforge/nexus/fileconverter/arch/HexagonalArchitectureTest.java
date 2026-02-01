```java
package com.opsforge.nexus.fileconverter.arch;

import com.tngtech.archunit.base.DescribedPredicate;
import com.tngtech.archunit.core.domain.JavaClasses;
import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.core.importer.ImportOption;
import com.tngtech.archunit.library.ArchClassification;
import com.tngtech.archunit.library.ArchRuleDefinition;
import com.tngtech.archunit.library.dependencies.SlicesRuleDefinition;
import com.tngtech.archunit.library.layers.LayeredArchitecture;
import com.tngtech.archunit.lang.ArchRule;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.stereotype.Repository;
import org.springframework.stereotype.Component;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * HexagonalArchitectureTest
 *
 * Ensures that the file-converter service adheres to the rules imposed by the
 * Hexagonal Architecture (a.k.a. Ports & Adapters) paradigm.
 *
 *  ┌───────────────────────────────────────────┐
 *  │               Incoming Ports              │
 *  │  (REST Controllers, GraphQL Resolvers…)   │
 *  └───────────────────────────────────────────┘
 *                    ▼
 *  ┌───────────────────────────────────────────┐
 *  │            Application Services           │
 *  │  (Use-cases orchestrating domain logic)   │
 *  └───────────────────────────────────────────┘
 *                    ▼
 *  ┌───────────────────────────────────────────┐
 *  │               Domain Model               │
 *  │         (Pure, technology-agnostic)      │
 *  └───────────────────────────────────────────┘
 *                    ▲
 *  ┌───────────────────────────────────────────┐
 *  │               Outgoing Ports              │
 *  │  (Persistence, External APIs, Caches…)    │
 *  └───────────────────────────────────────────┘
 */
@SuppressWarnings("squid:S1192") // allow repeated strings in package names for readability
class HexagonalArchitectureTest {

    /** Base package for the micro-service under test */
    private static final String BASE_PACKAGE = "com.opsforge.nexus.fileconverter";

    /** All production classes (test classes are filtered out) */
    private static JavaClasses classes;

    @BeforeAll
    static void setup() {
        classes = new ClassFileImporter()
                .withImportOption(ImportOption.Predefined.DO_NOT_INCLUDE_TESTS)
                .importPackages(BASE_PACKAGE);
    }

    /**
     * The definitive layered architecture for the File-Converter service.
     * <p>
     *     layer("Domain")            -> {@code ..domain..}<br />
     *     layer("Application")       -> {@code ..application..}<br />
     *     layer("Incoming Adapter")  -> {@code ..adapter.in..}<br />
     *     layer("Outgoing Adapter")  -> {@code ..adapter.out..}
     * </p>
     * Domain must not depend on anything.
     * Application may depend on Domain but not on adapters.
     * Incoming Adapter may depend on Application and Domain, never on Outgoing Adapter.
     * Outgoing Adapter may depend on Domain, never on Application nor Incoming Adapter.
     */
    @Test
    @DisplayName("01 – Layers do not violate Hexagonal Architecture boundaries")
    void verifyLayeredArchitecture() {

        LayeredArchitecture architecture = com.tngtech.archunit.library.ArchRuleDefinition
                .layeredArchitecture()
                .consideringAllDependencies()
                .layer("Domain").definedBy(BASE_PACKAGE + ".domain..")
                .layer("Application").definedBy(BASE_PACKAGE + ".application..")
                .layer("Incoming Adapter").definedBy(BASE_PACKAGE + ".adapter.in..")
                .layer("Outgoing Adapter").definedBy(BASE_PACKAGE + ".adapter.out..")

                // Domain is the innermost layer
                .whereLayer("Domain").mayOnlyBeAccessedByLayers("Application", "Incoming Adapter", "Outgoing Adapter")

                // Application sits between Domain and Adapters
                .whereLayer("Application").mayOnlyBeAccessedByLayers("Incoming Adapter")
                .whereLayer("Application").mayOnlyAccessLayers("Domain")

                // Incoming adapters may speak to Application + Domain
                .whereLayer("Incoming Adapter").mayNotBeAccessedByAnyLayer()
                .whereLayer("Incoming Adapter").mayOnlyAccessLayers("Application", "Domain")

                // Outgoing adapters may talk to Domain only
                .whereLayer("Outgoing Adapter").mayNotBeAccessedByAnyLayer()
                .whereLayer("Outgoing Adapter").mayOnlyAccessLayers("Domain");

        architecture.check(classes);
    }

    /**
     * Asserts that no cyclic package dependencies exist. Cycles in the import graph
     * are a notorious source of architectural decay.
     */
    @Test
    @DisplayName("02 – Service packages remain acyclic")
    void verifyNoCyclesBetweenPackages() {
        SlicesRuleDefinition.slices()
                .matching(BASE_PACKAGE + ".(*)..")
                .should()
                .beFreeOfCycles()
                .check(classes);
    }

    /**
     * Ensures that REST controllers live exclusively inside the
     * {@code adapter.in.web} package (or any sub-packages thereof).
     */
    @Test
    @DisplayName("03 – RestControllers reside in adapter.in.web")
    void controllersMustResideInCorrectPackage() {
        ArchRuleDefinition.classes()
                .that()
                .areAnnotatedWith(RestController.class)
                .should()
                .resideInAPackage(BASE_PACKAGE + ".adapter.in.web..")
                .andShould()
                .haveSimpleNameEndingWith("Controller")
                .check(classes);
    }

    /**
     * Ensures that Spring @Service beans that implement application use-cases
     * are located inside the {@code application} layer.
     */
    @Test
    @DisplayName("04 – Services reside in application package")
    void servicesMustResideInApplicationPackage() {
        ArchRuleDefinition.classes()
                .that()
                .areAnnotatedWith(Service.class)
                .should()
                .resideInAPackage(BASE_PACKAGE + ".application..")
                .check(classes);
    }

    /**
     * Ensures that repository implementations reside under {@code adapter.out.persistence}.
     */
    @Test
    @DisplayName("05 – Repositories reside in adapter.out.persistence")
    void repositoriesMustResideInPersistencePackage() {
        ArchRuleDefinition.classes()
                .that()
                .areAnnotatedWith(Repository.class)
                .should()
                .resideInAPackage(BASE_PACKAGE + ".adapter.out.persistence..")
                .check(classes);
    }

    /**
     * Makes sure utility classes (static helpers) do not hide state and
     * follow the typical Java utility-class pattern.
     */
    @Test
    @DisplayName("06 – Utility classes are well-formed")
    void utilityClassesShouldBeWellFormed() {
        DescribedPredicate<JavaClasses.JavaClass> isUtilityClass =
                javaClass -> javaClass.getSimpleName().endsWith("Utils") ||
                             javaClass.getSimpleName().endsWith("Constants");

        Set<JavaClasses.JavaClass> utilityClasses = classes.stream()
                .filter(isUtilityClass)
                .collect(Collectors.toSet());

        for (JavaClasses.JavaClass clazz : utilityClasses) {
            ArchRuleDefinition.classes()
                    .that()
                    .areAssignableTo(clazz.getFullName())
                    .should()
                    .haveOnlyFinalFields()
                    .andShould()
                    .haveOnlyPrivateConstructors()
                    .check(classes);
        }
    }

    /**
     * Prevent accidental injection of technical framework classes into the domain layer.
     */
    @Test
    @DisplayName("07 – Domain layer is free of Spring annotations")
    void domainLayerShouldNotDependOnSpring() {
        ArchRuleDefinition.noClasses()
                .that()
                .resideInAPackage(BASE_PACKAGE + ".domain..")
                .should()
                .dependOnClassesThat()
                .resideInAnyPackage(
                        "org.springframework..",
                        "com.fasterxml..",
                        "jakarta..",
                        "javax.."
                )
                .because("Domain model must stay pure and technology-agnostic")
                .check(classes);
    }

    /**
     * Ensures that components do not violate naming conventions:
     * – classes in {@code adapter.in.web} end with 'Controller'
     * – classes in {@code adapter.out.persistence} end with 'Repository'
     */
    @Test
    @DisplayName("08 – Naming conventions are respected")
    void namingConventionsMustBeRespected() {
        ArchRuleDefinition.classes()
                .that()
                .resideInAPackage(BASE_PACKAGE + ".adapter.in.web..")
                .should()
                .haveSimpleNameEndingWith("Controller")
                .check(classes);

        ArchRuleDefinition.classes()
                .that()
                .resideInAPackage(BASE_PACKAGE + ".adapter.out.persistence..")
                .should()
                .haveSimpleNameEndingWith("Repository")
                .check(classes);
    }

    /**
     * Validates that classes annotated with {@link Component} do not inadvertently
     * leak into the domain layer, where Spring should not be present.
     */
    @Test
    @DisplayName("09 – @Component is never used inside the domain package")
    void preventComponentsInDomainPackage() {
        ArchRuleDefinition.noClasses()
                .that()
                .areAnnotatedWith(Component.class)
                .should()
                .resideInAPackage(BASE_PACKAGE + ".domain..")
                .check(classes);
    }
}
```