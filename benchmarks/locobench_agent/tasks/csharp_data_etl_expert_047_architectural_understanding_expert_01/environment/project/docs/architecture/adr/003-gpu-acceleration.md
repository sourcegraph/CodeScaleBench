```csharp
// File: docs/architecture/adr/003-gpu-acceleration.md (Test Suite)
// NOTE: Although the original path is under /docs, the build treats this file as part of the test project.
//
// Purpose:
//   Validate the GPU-accelerated transformation layer (ComputeSharp integration) that powers
//   PaletteStream’s “high-chromatic” data pipelines.  These tests execute a representative
//   shader on supported hardware and fall back gracefully when no compatible GPU is available.
//
// NuGet (test-project) dependencies:
//   <PackageReference Include="ComputeSharp"             Version="2.3.0" />
//   <PackageReference Include="ComputeSharp.D2D1"        Version="2.3.0" />
//   <PackageReference Include="FluentAssertions"         Version="6.12.0" />
//   <PackageReference Include="xunit"                    Version="2.5.0" />
//   <PackageReference Include="xunit.runner.visualstudio" Version="2.5.0" />

using System;
using System.Diagnostics;
using System.Linq;
using ComputeSharp;
using FluentAssertions;
using Xunit;

namespace PaletteStream.DataEtl.Tests.GpuAcceleration
{
    /// <summary>
    /// End-to-end tests for GPU-accelerated transformations.
    /// </summary>
    public class GpuAccelerationTests
    {
        [Fact(DisplayName = "GPU device discovery works and default device is usable")]
        public void VerifyDefaultGpuDevice()
        {
            if (!HardwareAcceleration.IsGpuAvailable)
            {
                Skip.If(true, "No compatible GPU device detected on test host.");
            }

            var device = GraphicsDevice.GetDefault();
            device.Should().NotBeNull("ComputeSharp should return a usable default device.");

            // Basic smoke-test: allocate a tiny buffer.
            using var buffer = device.AllocateReadWriteBuffer<int>(4);
            buffer.Length.Should().Be(4);
        }

        [Fact(DisplayName = "Square shader executes correctly on GPU")]
        public void SquareShaderExecutesCorrectly()
        {
            var input  = Enumerable.Range(0, 1_000).Select(i => (float)i).ToArray();
            var output = HardwareAcceleration.SquareElements(input);

            output.Should().Equal(input.Select(x => x * x),
                                  "each element should be squared by the GPU shader");
        }

        [Fact(DisplayName = "GPU shader falls back gracefully when hardware is absent")]
        public void GracefulFallbackWhenGpuUnavailable()
        {
            // Temporarily force a "no-GPU" scenario for the scope of this test.
            // We use an environment variable so that the mutation doesn’t persist.
            const string flag = "PALETTEST_FORCE_NO_GPU";
            Environment.SetEnvironmentVariable(flag, "1");

            try
            {
                HardwareAcceleration.IsGpuAvailable.Should().BeFalse();
                var result = HardwareAcceleration.SquareElements(new[] { 2.0f });

                result.Should().Equal(new[] { 4.0f },
                    "CPU fallback should yield correct mathematical results.");
            }
            finally
            {
                Environment.SetEnvironmentVariable(flag, null); // Clean-up
            }
        }
    }

    /// <summary>
    /// Static utility class that encapsulates GPU detection and shader execution.
    /// </summary>
    internal static class HardwareAcceleration
    {
        private static readonly Lazy<bool> _isGpuSupported = new Lazy<bool>(() =>
        {
            // Test-time override for predictable behaviour.
            if (Environment.GetEnvironmentVariable("PALETTEST_FORCE_NO_GPU") == "1")
            {
                return false;
            }

            try
            {
                _ = GraphicsDevice.GetDefault();
                return true;
            }
            catch (Exception ex) when (ex is NotSupportedException or InvalidOperationException)
            {
                return false;
            }
        });

        /// <summary>
        /// Indicates whether a compatible ComputeSharp GPU device is available.
        /// </summary>
        public static bool IsGpuAvailable => _isGpuSupported.Value;

        /// <summary>
        /// Squares each element of <paramref name="input"/> using GPU acceleration when available.
        /// </summary>
        /// <exception cref="ArgumentNullException">Thrown if <paramref name="input"/> is null.</exception>
        public static float[] SquareElements(float[] input)
        {
            if (input is null) throw new ArgumentNullException(nameof(input));

            // Fast-path: GPU available
            if (IsGpuAvailable)
            {
                return SquareElementsOnGpu(input);
            }

            // Fallback: pure-CPU implementation
            return SquareElementsOnCpu(input);
        }

        #region Private helpers

        private static float[] SquareElementsOnGpu(float[] input)
        {
            var length = input.Length;
            var device = GraphicsDevice.GetDefault();

            using ReadOnlyBuffer<float>  inBuffer  = device.AllocateReadOnlyBuffer(input);
            using ReadWriteBuffer<float> outBuffer = device.AllocateReadWriteBuffer<float>(length);

            device.For(length, new SquareShader(inBuffer, outBuffer));

            return outBuffer.ToArray();
        }

        private static float[] SquareElementsOnCpu(float[] input)
        {
            var result = new float[input.Length];
            for (int i = 0; i < input.Length; i++)
            {
                result[i] = input[i] * input[i];
            }
            return result;
        }

        #endregion
    }

    /// <summary>
    /// A simple ComputeSharp compute shader that squares input values.
    /// </summary>
    /// <param name="input">Read-only input buffer.</param>
    /// <param name="output">Writable output buffer.</param>
    [AutoConstructor]
    internal readonly partial struct SquareShader : IComputeShader
    {
        public readonly ReadOnlyBuffer<float> Input;
        public readonly ReadWriteBuffer<float> Output;

        public void Execute()
        {
            int i = ThreadIds.X;
            Output[i] = Input[i] * Input[i];
        }
    }
}
```