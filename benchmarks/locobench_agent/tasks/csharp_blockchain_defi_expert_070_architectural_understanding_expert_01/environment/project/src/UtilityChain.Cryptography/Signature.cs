```csharp
// -----------------------------------------------------------------------------
// File: Signature.cs
// Project: UtilityChain Core Suite  (blockchain_defi)
// Description:
//   High-level API for signing and verifying messages across supported
//   asymmetric key schemes (Ed25519 & secp256k1).  The abstractions here are
//   kept intentionally generic so that call-sites inside the monolith do not
//   need to know which concrete algorithm they are using—enabling
//   plug-and-play cryptography through simple dependency-injection / IoC.
// -----------------------------------------------------------------------------

using System;
using System.Buffers;
using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;
using Org.BouncyCastle.Math;
using Org.BouncyCastle.Security;

namespace UtilityChain.Cryptography;

/// <summary>
/// Enumerates the asymmetric signature schemes understood by the framework.
/// </summary>
public enum SignatureScheme : byte
{
    /// <summary>EdDSA over Curve25519 with SHA-512 (RFC 8032)</summary>
    Ed25519 = 0x01,

    /// <summary>ECDSA over secp256k1 with SHA-256</summary>
    Secp256k1 = 0x02
}

/// <summary>
/// Represents an immutable cryptographic signature, including the scheme so that
/// consumers can verify without additional context.
/// </summary>
public readonly struct Signature : IEquatable<Signature>
{
    private readonly byte[] _raw;

    public SignatureScheme Scheme { get; }

    /// <summary>
    /// Raw signature bytes.  Depending on <see cref="Scheme"/> the format is:
    /// ‑ Ed25519 : 64-byte R || S
    /// ‑ Secp256k1 : DER-encoded sequence (per RFC 3279)
    /// </summary>
    public ReadOnlySpan<byte> Raw => _raw;

    public bool IsEmpty => _raw is null || _raw.Length == 0;

    public int Length => _raw?.Length ?? 0;

    public Signature(SignatureScheme scheme, ReadOnlySpan<byte> raw)
    {
        Scheme = scheme;
        _raw = raw.ToArray();
    }

    public override string ToString() => $"{Scheme}:{ToHex()}";

    public string ToBase64() => Convert.ToBase64String(_raw);

    public string ToHex() => Convert.ToHexString(_raw);

    public bool Equals(Signature other)
        => Scheme == other.Scheme && Raw.SequenceEqual(other.Raw);

    public override bool Equals([NotNullWhen(true)] object? obj)
        => obj is Signature sig && Equals(sig);

    public override int GetHashCode()
        => HashCode.Combine(Scheme, Length);

    public static bool operator ==(Signature left, Signature right) => left.Equals(right);
    public static bool operator !=(Signature left, Signature right) => !left.Equals(right);
}

/// <summary>
/// Abstraction over a concrete signature engine (Ed25519, secp256k1…).
/// </summary>
public interface ISignatureProvider
{
    /// <summary>Algorithm that this provider implements.</summary>
    SignatureScheme Scheme { get; }

    /// <summary>Signs <paramref name="message"/> with the given <paramref name="privateKey"/>.</summary>
    Signature Sign(ReadOnlySpan<byte> message, ReadOnlySpan<byte> privateKey);

    /// <summary>Validates <paramref name="signature"/> against <paramref name="message"/>.</summary>
    bool Verify(ReadOnlySpan<byte> message, ReadOnlySpan<byte> publicKey, Signature signature);
}

// ============================================================================
// Concrete Providers
// ============================================================================

internal sealed class Ed25519SignatureProvider : ISignatureProvider
{
    public SignatureScheme Scheme => SignatureScheme.Ed25519;

    public Signature Sign(ReadOnlySpan<byte> message, ReadOnlySpan<byte> privateKey)
    {
        if (privateKey.Length != 32)
            throw new ArgumentException("Ed25519 private key must be 32 bytes.", nameof(privateKey));

        Span<byte> sig = stackalloc byte[64];
        bool ok = CryptographicOperations.TrySign(privateKey, message, sig, out _);
        if (!ok)
            throw new CryptographicException("Failed to produce Ed25519 signature.");

        return new Signature(Scheme, sig);
    }

    public bool Verify(ReadOnlySpan<byte> message, ReadOnlySpan<byte> publicKey, Signature signature)
    {
        if (publicKey.Length != 32)
            return false;
        if (signature.Scheme != Scheme || signature.Length != 64)
            return false;

        return CryptographicOperations.VerifySignature(
            publicKey, message, signature.Raw, out _);
    }
}

internal sealed class Secp256k1SignatureProvider : ISignatureProvider
{
    public SignatureScheme Scheme => SignatureScheme.Secp256k1;

    public Signature Sign(ReadOnlySpan<byte> message, ReadOnlySpan<byte> privateKey)
    {
        if (privateKey.Length != 32)
            throw new ArgumentException("secp256k1 private key must be 32 bytes.", nameof(privateKey));

        using var sha = SHA256.Create();
        byte[] hash = sha.ComputeHash(message.ToArray());

        var privBigInt = new BigInteger(1, privateKey.ToArray());
        var privParams = new ECPrivateKeyParameters(privBigInt, SecpParameters);

        var signer = new ECDsaSigner();
        signer.Init(true, privParams);
        var components = signer.GenerateSignature(hash);

        // DER encode (r, s)
        var seq = new DerSequenceGenerator();
        seq.AddObject(new Org.BouncyCastle.Asn1.DerInteger(components[0]));
        seq.AddObject(new Org.BouncyCastle.Asn1.DerInteger(components[1]));
        byte[] der = seq.Generate();

        return new Signature(Scheme, der);
    }

    public bool Verify(ReadOnlySpan<byte> message, ReadOnlySpan<byte> publicKey, Signature signature)
    {
        if (signature.Scheme != Scheme)
            return false;

        try
        {
            using var sha = SHA256.Create();
            byte[] hash = sha.ComputeHash(message.ToArray());

            var q = SecpParameters.Curve.DecodePoint(publicKey.ToArray());
            var pubParams = new ECPublicKeyParameters(q, SecpParameters);

            var signer = new ECDsaSigner();
            signer.Init(false, pubParams);

            // Decode DER
            var seq = (Org.BouncyCastle.Asn1.Asn1Sequence)Org.BouncyCastle.Asn1.Asn1Object.FromByteArray(signature.Raw.ToArray());
            var r = ((Org.BouncyCastle.Asn1.DerInteger)seq[0]).PositiveValue;
            var s = ((Org.BouncyCastle.Asn1.DerInteger)seq[1]).PositiveValue;

            return signer.VerifySignature(hash, r, s);
        }
        catch
        {
            return false;
        }
    }

    private static readonly ECDomainParameters SecpParameters;

    static Secp256k1SignatureProvider()
    {
        var curve = Org.BouncyCastle.Asn1.Sec.SecObjectIdentifiers.Secp256k1;
        var ecParams = Org.BouncyCastle.Asn1.Sec.SecNamedCurves.GetByOid(curve);
        SecpParameters = new ECDomainParameters(ecParams.Curve, ecParams.G, ecParams.N, ecParams.H);
    }
}

// ============================================================================
// Facade – used by the rest of the system
// ============================================================================

/// <summary>
/// Composite service that dispatches operations to the correct provider given
/// a signature scheme.  The class may be registered as a singleton in DI.
/// </summary>
public sealed class SignatureService
{
    private readonly ISignatureProvider[] _providers;

    public SignatureService()
        : this(new ISignatureProvider[]
        {
            new Ed25519SignatureProvider(),
            new Secp256k1SignatureProvider()
        })
    { }

    public SignatureService(params ISignatureProvider[] providers)
    {
        if (providers is null || providers.Length == 0)
            throw new ArgumentException("At least one signature provider must be supplied.", nameof(providers));

        _providers = providers;
    }

    /// <summary>
    /// Sign the supplied <paramref name="message"/> with <paramref name="privateKey"/>
    /// using <paramref name="scheme"/>.
    /// </summary>
    public Signature Sign(SignatureScheme scheme, ReadOnlySpan<byte> message, ReadOnlySpan<byte> privateKey)
        => GetProvider(scheme).Sign(message, privateKey);

    /// <summary>
    /// Verify <paramref name="signature"/> for <paramref name="message"/> with
    /// <paramref name="publicKey"/>.
    /// </summary>
    public bool Verify(ReadOnlySpan<byte> message, ReadOnlySpan<byte> publicKey, Signature signature)
        => GetProvider(signature.Scheme).Verify(message, publicKey, signature);

    /// <summary>
    /// Retrieves a provider for the requested <paramref name="scheme"/> or throws
    /// an exception if unavailable.
    /// </summary>
    private ISignatureProvider GetProvider(SignatureScheme scheme)
    {
        foreach (var p in _providers)
            if (p.Scheme == scheme) return p;

        throw new NotSupportedException($"Signature scheme '{scheme}' is not supported.");
    }
}

// ============================================================================
// Internal helpers
// ============================================================================

internal static class CryptographicOperations
{
#if NET8_0_OR_GREATER
    // Ed25519 support is built-in starting .NET 8.
    public static bool TrySign(ReadOnlySpan<byte> privateKey, ReadOnlySpan<byte> data,
        Span<byte> destination, out int bytesWritten)
    {
        // Destination must be 64 bytes for Ed25519
        if (destination.Length < 64)
        {
            bytesWritten = 0;
            return false;
        }

        try
        {
            using var ed = new Ed25519PrivateKey(privateKey);
            ed.Sign(data, destination);
            bytesWritten = 64;
            return true;
        }
        catch
        {
            bytesWritten = 0;
            return false;
        }
    }

    public static bool VerifySignature(ReadOnlySpan<byte> publicKey, ReadOnlySpan<byte> data,
        ReadOnlySpan<byte> signature, out Exception? error)
    {
        error = null;
        try
        {
            using var ed = new Ed25519PublicKey(publicKey);
            return ed.Verify(data, signature);
        }
        catch (Exception ex)
        {
            error = ex;
            return false;
        }
    }

    // Minimal wrappers around built-in types to keep the rest of the file clean.
    private sealed class Ed25519PrivateKey : IDisposable
    {
        private readonly PrivateKeyInfo _info;
        private readonly AsymmetricAlgorithm _algo;

        public Ed25519PrivateKey(ReadOnlySpan<byte> key)
        {
            _info = new PrivateKeyInfo(key.ToArray());
            _algo = ECDiffieHellman.Create();
        }

        public void Sign(ReadOnlySpan<byte> data, Span<byte> destination)
        {
            _algo.SignData(data, destination, HashAlgorithmName.SHA512);
        }

        public void Dispose() => _algo.Dispose();
    }

    private sealed class Ed25519PublicKey : IDisposable
    {
        private readonly AsymmetricAlgorithm _algo;

        public Ed25519PublicKey(ReadOnlySpan<byte> key)
        {
            _algo = ECDiffieHellman.Create();
            _algo.ImportSubjectPublicKeyInfo(key, out _);
        }

        public bool Verify(ReadOnlySpan<byte> data, ReadOnlySpan<byte> signature)
            => _algo.VerifyData(data, signature, HashAlgorithmName.SHA512);

        public void Dispose() => _algo.Dispose();
    }
#else
    // Fallback for older runtimes: you could wire up libsodium here.
    public static bool TrySign(ReadOnlySpan<byte> privateKey, ReadOnlySpan<byte> data,
        Span<byte> destination, out int bytesWritten)
        => throw new PlatformNotSupportedException(".NET 8 or higher required for Ed25519.");

    public static bool VerifySignature(ReadOnlySpan<byte> publicKey, ReadOnlySpan<byte> data,
        ReadOnlySpan<byte> signature, out Exception? error)
        => throw new PlatformNotSupportedException(".NET 8 or higher required for Ed25519.");
#endif
}
```