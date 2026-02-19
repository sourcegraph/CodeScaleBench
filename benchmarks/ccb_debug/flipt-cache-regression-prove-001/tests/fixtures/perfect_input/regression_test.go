package main

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"testing"
	"time"

	authpkg "go.flipt.io/flipt/internal/server/auth"
	authrpc "go.flipt.io/flipt/rpc/flipt/auth"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

// fakeAuthenticator implements auth.Authenticator for testing.
type fakeAuthenticator struct{}

func (f *fakeAuthenticator) Authenticate(ctx context.Context, token string) (*authrpc.Authentication, error) {
	if token == "valid-token" {
		return &authrpc.Authentication{Id: "test-auth"}, nil
	}
	return nil, status.Error(codes.Unauthenticated, "invalid token")
}

// fakeHandler is a no-op unary handler for interceptor testing.
func fakeHandler(ctx context.Context, req interface{}) (interface{}, error) {
	return "ok", nil
}

func TestRegression(t *testing.T) {
	logger := zap.NewNop()
	auth := &fakeAuthenticator{}

	t.Run("cookie_based_token_extraction", func(t *testing.T) {
		// Test that a valid client token stored in an HTTP cookie is
		// correctly extracted and authenticated by the middleware.
		interceptor := authpkg.UnaryInterceptor(logger, auth)

		// Simulate a gRPC request with a cookie header containing the
		// flipt_client_token. This is what browsers send.
		cookie := &http.Cookie{
			Name:  "flipt_client_token",
			Value: "valid-token",
		}
		md := metadata.MD{
			"grpcgateway-cookie": {cookie.String()},
		}
		ctx := metadata.NewIncomingContext(context.Background(), md)

		info := &grpc.UnaryServerInfo{
			FullMethod: "/flipt.Flipt/GetFlag",
		}

		_, err := interceptor(ctx, nil, info, fakeHandler)
		if err != nil {
			st, ok := status.FromError(err)
			if ok && st.Code() == codes.Unauthenticated {
				t.Fatalf("cookie-based token was rejected as unauthenticated: %v", err)
			}
			t.Fatalf("unexpected error: %v", err)
		}
	})

	t.Run("server_skip_authentication", func(t *testing.T) {
		// Test that a server instance registered with
		// WithServerSkipsAuthentication is not subject to authentication.
		type testServer struct{}
		srv := &testServer{}

		interceptor := authpkg.UnaryInterceptor(
			logger,
			auth,
			authpkg.WithServerSkipsAuthentication(srv),
		)

		// No authentication metadata at all — should still succeed
		// because this server is configured to skip auth.
		ctx := metadata.NewIncomingContext(
			context.Background(),
			metadata.MD{},
		)

		info := &grpc.UnaryServerInfo{
			Server:     srv,
			FullMethod: "/flipt.auth.AuthenticationService/GetAuthToken",
		}

		_, err := interceptor(ctx, nil, info, fakeHandler)
		if err != nil {
			t.Fatalf("server skip authentication failed: %v", err)
		}
	})
}
