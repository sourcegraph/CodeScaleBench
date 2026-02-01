```javascript
/**
 * Integration tests for the Auth-Service.
 *
 * These tests spin up an in-memory MongoDB instance, boot the real Express
 * application (no stubbing of HTTP layer) and exercise the public REST API.
 *
 * We deliberately avoid mocking business logic so that we can assert on real
 * DB state, JWT issuance, cookie behaviour, and error handling contracts.
 *
 * Run with:
 *   $ NODE_ENV=test npx jest services/auth-service/test/integration/auth.test.js
 */

const request = require('supertest');
const jwt = require('jsonwebtoken');
const mongoose = require('mongoose');
const { MongoMemoryServer } = require('mongodb-memory-server');
const { v4: uuid } = require('uuid');

const createApp = require('../../src/app'); // factory that returns an Express app
const User = require('../../src/models/user'); // Mongoose model

// ---------------------------- helpers ---------------------------------------

/**
 * Creates a JWT with the same secret the service uses.
 * This is handy when we need to craft “foreign” tokens (e.g. invalid sig)
 */
const signJwt = (payload, opts = {}) => {
  const secret = process.env.JWT_SECRET || 'test-secret';
  return jwt.sign(payload, secret, { expiresIn: '10m', ...opts });
};

/**
 * Wait helper for async retries (e.g. event propagation).
 */
const delay = (ms = 25) => new Promise((res) => setTimeout(res, ms));

// -------------------------- test suite --------------------------------------

describe('Auth Service – Integration', () => {
  let mongo;
  let app;
  let server;          // supertest.Server
  let agent;           // supertest agent (maintains cookie jar)

  // -------------------------------------------------------------------------
  // Life-cycle
  // -------------------------------------------------------------------------

  beforeAll(async () => {
    /**
     * MongoMemoryServer gives us an isolated DB per test run with no external
     * dependency. We can freely seed fixtures without polluting dev/prod data.
     */
    mongo = await MongoMemoryServer.create();
    const uri = mongo.getUri();

    await mongoose.connect(uri, {
      useNewUrlParser: true,
      useUnifiedTopology: true,
    });

    app = createApp();               // build the real app
    server = request(app);
    agent = request.agent(app);      // cookie-aware client
  });

  afterAll(async () => {
    await mongoose.connection.close();
    await mongo.stop();
  });

  afterEach(async () => {
    // Clean DB between tests to preserve isolation and deterministic state.
    await Promise.all([
      User.deleteMany({}),
    ]);
  });

  // -------------------------------------------------------------------------
  // Test cases
  // -------------------------------------------------------------------------

  describe('POST /auth/register', () => {
    it('creates a new user and returns JWT + refresh cookie', async () => {
      const payload = {
        email: `student+${uuid()}@pulselearn.io`,
        password: 'Sup3r-Secr3t!',
        name: 'Test Student',
      };

      const res = await server.post('/auth/register').send(payload);

      expect(res.statusCode).toBe(201);
      expect(res.body).toHaveProperty('accessToken');
      expect(res.headers['set-cookie']).toEqual(
        expect.arrayContaining([
          expect.stringContaining('refreshToken='),
        ]),
      );

      // Validate DB insert
      const userInDb = await User.findOne({ email: payload.email });
      expect(userInDb).not.toBeNull();
      expect(userInDb.name).toBe(payload.name);

      // Validate JWT payload
      const decoded = jwt.decode(res.body.accessToken);
      expect(decoded.sub).toEqual(userInDb.id.toString());
    });

    it('rejects duplicate email registration with 409', async () => {
      const email = `duplicate@pulselearn.io`;
      await User.create({
        email,
        passwordHash: 'irrelevant',
        name: 'Existing',
      });

      const res = await server.post('/auth/register').send({
        email,
        password: 'DoesNotMatter',
        name: 'Someone',
      });

      expect(res.statusCode).toBe(409);
      expect(res.body.error).toMatch(/exists/i);
    });
  });

  describe('POST /auth/login', () => {
    const credentials = {
      email: `login-student@pulselearn.io`,
      password: 'A!very$trongPass',
    };

    beforeEach(async () => {
      await server.post('/auth/register').send({
        ...credentials,
        name: 'Login Student',
      });
    });

    it('logs in with correct credentials and sets refresh cookie', async () => {
      const res = await agent.post('/auth/login').send(credentials);

      expect(res.statusCode).toBe(200);
      expect(res.body).toHaveProperty('accessToken');
      expect(res.headers['set-cookie']).toEqual(
        expect.arrayContaining([expect.stringMatching(/refreshToken=.*HttpOnly/)]),
      );
    });

    it('rejects invalid password with 401', async () => {
      const res = await server.post('/auth/login').send({
        ...credentials,
        password: 'incorrect',
      });

      expect(res.statusCode).toBe(401);
      expect(res.body.error).toMatch(/invalid/i);
    });
  });

  describe('GET /auth/me', () => {
    let accessToken;

    beforeEach(async () => {
      const payload = {
        email: `me-route@pulselearn.io`,
        password: 'St@blePassword1',
        name: 'Who Am I',
      };
      const registerRes = await server.post('/auth/register').send(payload);
      accessToken = registerRes.body.accessToken;
    });

    it('returns current user when valid JWT is supplied', async () => {
      const res = await server
        .get('/auth/me')
        .set('Authorization', `Bearer ${accessToken}`);

      expect(res.statusCode).toBe(200);
      expect(res.body).toMatchObject({
        email: expect.any(String),
        name: expect.any(String),
        id: expect.any(String),
      });
    });

    it('returns 401 when token is expired/invalid', async () => {
      const forgedToken = signJwt({ sub: mongoose.Types.ObjectId() }, { expiresIn: '-1s' });

      const res = await server
        .get('/auth/me')
        .set('Authorization', `Bearer ${forgedToken}`);

      expect(res.statusCode).toBe(401);
    });
  });

  describe('POST /auth/refresh', () => {
    let refreshTokenCookie;
    let firstAccessToken;

    beforeEach(async () => {
      const res = await agent.post('/auth/register').send({
        email: `refresh-flow@pulselearn.io`,
        password: '#SeCret123',
        name: 'Refresh Flow',
      });

      // Save tokens
      firstAccessToken = res.body.accessToken;
      refreshTokenCookie = res.headers['set-cookie'].find((c) =>
        c.startsWith('refreshToken='),
      );
    });

    it('issues new access token when valid refresh cookie provided', async () => {
      const res = await agent
        .post('/auth/refresh')
        .set('Cookie', refreshTokenCookie)
        .send();

      expect(res.statusCode).toBe(200);
      expect(res.body).toHaveProperty('accessToken');
      expect(res.body.accessToken).not.toEqual(firstAccessToken);
    });

    it('denies refresh when cookie is missing or invalid', async () => {
      const res = await server.post('/auth/refresh').send();
      expect(res.statusCode).toBe(401);

      const invalidCookie = 'refreshToken=totallyInvalid; HttpOnly';
      const res2 = await server.post('/auth/refresh').set('Cookie', invalidCookie).send();
      expect(res2.statusCode).toBe(401);
    });
  });

  describe('POST /auth/logout', () => {
    it('clears refresh token cookie', async () => {
      const registerRes = await agent.post('/auth/register').send({
        email: `logout@pulselearn.io`,
        password: '^LogoutPass8',
        name: 'Logout User',
      });

      expect(registerRes.headers['set-cookie']).toEqual(
        expect.arrayContaining([expect.stringMatching(/^refreshToken=/)]),
      );

      const logoutRes = await agent.post('/auth/logout').send();

      expect(logoutRes.statusCode).toBe(204);
      // Verify cookie is cleared
      expect(logoutRes.headers['set-cookie']).toEqual(
        expect.arrayContaining([
          expect.stringMatching(/refreshToken=;.*Max-Age=0/),
        ]),
      );
    });
  });

  describe('POST /auth/social/:provider', () => {
    // We stub out the upstream OAuth provider so the service runs in “fake”
    // mode (configurable via env var). This allows us to test the rest of the
    // pipeline: user creation, JWT issuance, session creation, analytics.
    const provider = 'google';

    beforeAll(() => {
      process.env.OAUTH_FAKE_MODE = 'true'; // service looks for this
    });

    afterAll(() => {
      delete process.env.OAUTH_FAKE_MODE;
    });

    it('registers/logs-in user via OAuth and returns tokens', async () => {
      const oauthPayload = {
        authorizationCode: 'fake-auth-code',
        redirectUri: 'https://pulselearn.io/auth/callback',
      };

      const res = await server.post(`/auth/social/${provider}`).send(oauthPayload);

      expect(res.statusCode).toBe(200);
      expect(res.body).toHaveProperty('accessToken');
      expect(res.headers['set-cookie']).toEqual(
        expect.arrayContaining([expect.stringContaining('refreshToken=')]),
      );

      // The user should exist exactly once
      const jwtPayload = jwt.decode(res.body.accessToken);
      const userId = jwtPayload.sub;

      const userCount = await User.countDocuments({ _id: userId });
      expect(userCount).toBe(1);
    });
  });
});
```