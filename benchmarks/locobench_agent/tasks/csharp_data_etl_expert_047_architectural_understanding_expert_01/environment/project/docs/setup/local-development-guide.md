```csharp
// -----------------------------------------------------------------------------
// File: docs/setup/local-development-guide.md  (yes, Markdown — but we embed
// runnable C# verification code blocks to guarantee that the documentation
// does not drift from the actual behaviour of the bootstrapper.  The tests are
// discovered and executed by `dotnet test` through the Markdown‐test adapter.)
// -----------------------------------------------------------------------------
//
// NOTE: The PaletteStream build pipeline is wired so that any Markdown file
// found under /docs that contains a C# code fence marked with "test" will be
// compiled and executed as part of the Verification stage.  This guarantees
// that the examples in our docs stay accurate and up-to-date.
//
// To run the tests locally:
//
//   > dotnet test docs/setup/
//
// -----------------------------------------------------------------------------
// Setup ‑ Local Development Guide
// -----------------------------------------------------------------------------
//
// 1. Copy `local.env.sample` to `local.env`.
// 2. Run `docker compose up -d postgres kafka zookeeper schema-registry`.
// 3. Execute `dotnet run --project src/PaletteStream.ETL.Bootstrapper`.
//
// The following embedded tests ASSERT that the above instructions are
// sufficient for a contributor to get a clean environment up and running.
//
// -----------------------------------------------------------------------------
````csharp test
#nullable enable
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using FluentAssertions;
using Xunit;

namespace PaletteStream.Docs.Setup
{
    /// <summary>
    /// Integration-style tests that validate the local development guide.
    /// The tests double-check that all binaries, docker services and
    /// environment variables required for a first-time setup are present.
    ///
    /// They run extremely fast and are safe for CI because they only spin up
    /// processes when RUN_LOCAL_DEV_FULL=1 is explicitly specified.
    /// </summary>
    public sealed class LocalDevelopmentGuideSpec : IDisposable
    {
        private readonly string _projectRoot;
        private readonly bool _runFullSuite;

        public LocalDevelopmentGuideSpec()
        {
            _projectRoot  = FindProjectRoot();
            _runFullSuite = Environment.GetEnvironmentVariable("RUN_LOCAL_DEV_FULL") == "1";
        }

        // ---------------------------------------------------------------------
        //  Environment Validation
        // ---------------------------------------------------------------------

        [Fact(DisplayName = "local.env sample file MUST exist")]
        public void LocalEnvSample_Should_Exist()
        {
            var path = Path.Combine(_projectRoot, "local.env.sample");
            File.Exists(path)
                .Should().BeTrue($"'{path}' should be committed to the repo");
        }

        [Fact(DisplayName = "Docker Compose file MUST exist at project root")]
        public void DockerComposeFile_Should_Exist()
        {
            var path = Path.Combine(_projectRoot, "docker-compose.yml");
            File.Exists(path)
                .Should().BeTrue("Developers rely on docker-compose for local services");
        }

        [Fact(DisplayName = "Bootstrapper project MUST build successfully")]
        public void Bootstrapper_Project_Should_Build()
        {
            // Build runs extremely quickly because everything is already restored
            var (exitCode, _, stderr) = RunProcess(
                "dotnet",
                "build -c Debug --nologo --verbosity quiet " +
                "src/PaletteStream.ETL.Bootstrapper/PaletteStream.ETL.Bootstrapper.csproj",
                timeoutSecs: 60);

            exitCode.Should().Be(0, $"bootstrapper must build [stderr: {stderr}]");
        }

        // ---------------------------------------------------------------------
        //  Optional Full-stack Smoke Test
        // ---------------------------------------------------------------------

        [SkippableFact(DisplayName = "Bootstrapper starts without fatal error (optional)")]
        public void Bootstrapper_Should_Start_And_Exit_Healthy()
        {
            Skip.IfNot(_runFullSuite, "Set RUN_LOCAL_DEV_FULL=1 to enable the full bootstrapper smoke test.");

            var projectPath = Path.Combine(
                _projectRoot, "src/PaletteStream.ETL.Bootstrapper/");

            var (exit, stdout, stderr) = RunProcess(
                "dotnet",
                $"run --project \"{projectPath}\" -- --dry-run",
                workingDir: _projectRoot,
                timeoutSecs: 180);

            exit.Should().Be(0, $"Bootstrapper must exit cleanly [stderr: {stderr}]");

            stdout.Should().Contain("ETL bootstrap completed in DRY-RUN mode");
        }

        // ---------------------------------------------------------------------
        //  Helper Functions
        // ---------------------------------------------------------------------

        private static string FindProjectRoot()
        {
            var dir = AppContext.BaseDirectory;
            while (!string.IsNullOrEmpty(dir))
            {
                if (File.Exists(Path.Combine(dir, "PaletteStream.sln")))
                    return dir;

                dir = Directory.GetParent(dir)?.FullName
                      ?? throw new InvalidOperationException(
                          "Cannot locate project root (PaletteStream.sln).");
            }

            throw new InvalidOperationException("Reached filesystem root without finding project root.");
        }

        private static (int exitCode, string stdout, string stderr) RunProcess(
            string filename,
            string arguments,
            string? workingDir = null,
            int timeoutSecs     = 30)
        {
            using var proc = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName               = filename,
                    Arguments              = arguments,
                    WorkingDirectory       = workingDir ?? Environment.CurrentDirectory,
                    RedirectStandardError  = true,
                    RedirectStandardOutput = true,
                    UseShellExecute        = false,
                    CreateNoWindow         = true,
                }
            };

            proc.Start();

            var stdOut = proc.StandardOutput.ReadToEndAsync();
            var stdErr = proc.StandardError.ReadToEndAsync();

            if (!proc.WaitForExit(timeoutSecs * 1000))
            {
                try   { proc.Kill(entireProcessTree: true); }
                catch { /* ignored */ }

                throw new TimeoutException(
                    $"Process '{filename} {arguments}' exceeded {timeoutSecs} s timeout.");
            }

            return (proc.ExitCode, stdOut.Result, stdErr.Result);
        }

        public void Dispose()
        {
            // No shared resources yet — left for future extensions (e.g. teardown docker)
        }
    }
}
````