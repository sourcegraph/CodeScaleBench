```javascript
/**
 * PulseLearn Campus Hub – Auth Service
 *
 * Single–entry bootstrap file that wires together:
 *  • Express REST API
 *  • Sequelize ORM (PostgreSQL)
 *  • Passport strategies (JWT / Google OAuth 2.0)
 *  • KafkaJS producer for domain events
 *  • Hardened security / observability middle-wares
 *
 * NOTE:
 *  This file purposefully contains bootstrap, infra-plumbing and a minimal
 *  controller to keep the snippet self-contained for demonstration.  In a real
 *  world code-base these concerns would be split across dedicated modules.
 */

/* ──────────────────────────────────────────────────────────────────────────
 * External Dependencies
 * ────────────────────────────────────────────────────────────────────────── */
const express          = require('express');
const helmet           = require('helmet');
const cors             = require('cors');
const morgan           = require('morgan');
const cookieParser     = require('cookie-parser');
const passport         = require('passport');
const { Strategy: JwtStrategy, ExtractJwt }            = require('passport-jwt');
const { Strategy: GoogleStrategy }                     = require('passport-google-oauth20');
const jwt              = require('jsonwebtoken');
const { Sequelize, DataTypes, Op } = require('sequelize');
const { Kafka }        = require('kafkajs');
const http             = require('http');
const crypto           = require('crypto');

/* ──────────────────────────────────────────────────────────────────────────
 * Environment & Configuration
 * ────────────────────────────────────────────────────────────────────────── */
require('dotenv').config(); // Loads .env vars into process.env

const CONFIG = {
    PORT:                    process.env.PORT                     || 4000,
    NODE_ENV:                process.env.NODE_ENV                 || 'development',
    JWT_SECRET:              process.env.JWT_SECRET               || crypto.randomBytes(32).toString('hex'),
    JWT_EXPIRES_IN:          process.env.JWT_EXPIRES_IN           || '6h',
    GOOGLE_CLIENT_ID:        process.env.GOOGLE_CLIENT_ID         || '',
    GOOGLE_CLIENT_SECRET:    process.env.GOOGLE_CLIENT_SECRET     || '',
    GOOGLE_CALLBACK_URL:     process.env.GOOGLE_CALLBACK_URL      || '/auth/google/callback',
    POSTGRES_URI:            process.env.POSTGRES_URI             || 'postgres://pl:pl@localhost:5432/pulselearn_auth',
    KAFKA_BROKERS:           (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
    KAFKA_CLIENT_ID:         process.env.KAFKA_CLIENT_ID || 'pulselearn-auth-service',
    EVENT_TOPIC:             'pl.auth.events',
    CORS_ORIGINS:            (process.env.CORS_ORIGINS || '*').split(','),
};

/* ──────────────────────────────────────────────────────────────────────────
 * Database Setup via Sequelize
 * ────────────────────────────────────────────────────────────────────────── */

const sequelize = new Sequelize(CONFIG.POSTGRES_URI, {
    dialect: 'postgres',
    logging: CONFIG.NODE_ENV === 'development' ? console.log : false,
    pool:    { min: 1, max: 10, acquire: 30000, idle: 10000 }
});

// User model (simplified)
const User = sequelize.define('user', {
    id:            { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    email:         { type: DataTypes.STRING(320), unique: true, allowNull: false, validate: { isEmail: true } },
    passwordHash:  { type: DataTypes.STRING, allowNull: true }, // Null for social logins
    displayName:   { type: DataTypes.STRING(128) },
    avatarUrl:     { type: DataTypes.STRING(2048) },
    provider:      { type: DataTypes.STRING(32), defaultValue: 'local' },
    providerId:    { type: DataTypes.STRING(128) } // Google / Facebook ID etc.
}, { underscored: true, paranoid: true, timestamps: true });

/* ──────────────────────────────────────────────────────────────────────────
 * Event Bus (Kafka) – Producer
 * ────────────────────────────────────────────────────────────────────────── */
const kafka      = new Kafka({ clientId: CONFIG.KAFKA_CLIENT_ID, brokers: CONFIG.KAFKA_BROKERS });
const producer   = kafka.producer();

/**
 * Publishes an auth domain event to Kafka asynchronously.
 * @param {string} type - Domain event name (e.g., UserRegistered)
 * @param {object} payload - Arbitrary JSON-serialisable payload
 */
async function publishEvent(type, payload) {
    try {
        await producer.send({
            topic: CONFIG.EVENT_TOPIC,
            messages: [{ key: type, value: JSON.stringify({ type, payload, timestamp: Date.now() }) }]
        });
    } catch (err) {
        console.error('Failed to publish Kafka event', err);
    }
}

/* ──────────────────────────────────────────────────────────────────────────
 * Passport Strategies
 * ────────────────────────────────────────────────────────────────────────── */

// JWT – stateless auth for REST endpoints
passport.use(new JwtStrategy({
    jwtFromRequest: ExtractJwt.fromAuthHeaderAsBearerToken(),
    secretOrKey:    CONFIG.JWT_SECRET,
    algorithms:     ['HS256']
}, async (jwtPayload, done) => {
    try {
        const user = await User.findByPk(jwtPayload.sub);
        return done(null, user || false);
    } catch (err) {
        return done(err, false);
    }
}));

// Google OAuth 2.0 – social login
if (CONFIG.GOOGLE_CLIENT_ID && CONFIG.GOOGLE_CLIENT_SECRET) {
    passport.use(new GoogleStrategy({
        clientID:          CONFIG.GOOGLE_CLIENT_ID,
        clientSecret:      CONFIG.GOOGLE_CLIENT_SECRET,
        callbackURL:       CONFIG.GOOGLE_CALLBACK_URL,
        passReqToCallback: false,
    }, async (_accessToken, _refreshToken, profile, done) => {
        try {
            let user = await User.findOne({
                where: {
                    [Op.and]: [
                        { provider: 'google' },
                        { providerId: profile.id }
                    ]
                }
            });
            if (!user) {
                user = await User.create({
                    email:       profile.emails?.[0]?.value,
                    displayName: profile.displayName,
                    avatarUrl:   profile.photos?.[0]?.value,
                    provider:    'google',
                    providerId:  profile.id
                });
                publishEvent('UserRegistered', { userId: user.id, method: 'google' });
            }
            return done(null, user);
        } catch (err) {
            return done(err);
        }
    }));
}

// Serialisation (not used for JWT but required by Passport)
passport.serializeUser((user, done) => done(null, user.id));
passport.deserializeUser(async (id, done) => {
    const user = await User.findByPk(id);
    done(null, user);
});

/* ──────────────────────────────────────────────────────────────────────────
 * Express App Factory
 * ────────────────────────────────────────────────────────────────────────── */
function buildApp() {
    const app = express();
    app.disable('x-powered-by');

    /* Middleware Stack */
    app.use(helmet());
    app.use(cors({ origin: CONFIG.CORS_ORIGINS, credentials: true }));
    app.use(morgan(CONFIG.NODE_ENV === 'development' ? 'dev' : 'combined'));
    app.use(express.json({ limit: '1mb' }));
    app.use(express.urlencoded({ extended: false }));
    app.use(cookieParser());
    app.use(passport.initialize());

    /* Health-check Endpoint */
    app.get('/_health', (_req, res) => res.json({ status: 'ok', service: 'auth', timestamp: Date.now() }));

    /* ───────────── Auth Routes ───────────── */

    /**
     * POST /auth/register
     * Registers a user with email/password.
     */
    app.post('/auth/register', async (req, res, next) => {
        try {
            const { email, password, displayName } = req.body;
            if (!email || !password) {
                return res.status(400).json({ error: 'Email and password are required.' });
            }
            const existing = await User.findOne({ where: { email } });
            if (existing) {
                return res.status(409).json({ error: 'Email already registered.' });
            }
            const passwordHash = crypto
                .createHash('sha256')
                .update(password + CONFIG.JWT_SECRET) // simple hash for demo; in prod use bcrypt/scrypt/argon2
                .digest('hex');

            const user = await User.create({
                email,
                passwordHash,
                displayName,
                provider: 'local'
            });

            publishEvent('UserRegistered', { userId: user.id, method: 'local' });

            return res.status(201).json({ message: 'Registration successful.' });
        } catch (err) { return next(err); }
    });

    /**
     * POST /auth/login
     * Authenticates using email/password and returns a JWT.
     */
    app.post('/auth/login', async (req, res, next) => {
        try {
            const { email, password } = req.body;
            if (!email || !password) {
                return res.status(400).json({ error: 'Email and password are required.' });
            }
            const user = await User.findOne({ where: { email, provider: 'local' } });
            if (!user) {
                return res.status(401).json({ error: 'Invalid credentials.' });
            }
            const passwordHash = crypto.createHash('sha256').update(password + CONFIG.JWT_SECRET).digest('hex');
            if (passwordHash !== user.passwordHash) {
                return res.status(401).json({ error: 'Invalid credentials.' });
            }
            const token = jwt.sign(
                { sub: user.id, email: user.email, role: 'user' },
                CONFIG.JWT_SECRET,
                { expiresIn: CONFIG.JWT_EXPIRES_IN }
            );
            publishEvent('UserLoggedIn', { userId: user.id });
            return res.json({ token, expiresIn: CONFIG.JWT_EXPIRES_IN });
        } catch (err) { return next(err); }
    });

    /**
     * GET /auth/google
     * Initiates Google OAuth 2.0 login.
     */
    if (CONFIG.GOOGLE_CLIENT_ID && CONFIG.GOOGLE_CLIENT_SECRET) {
        app.get('/auth/google',
            passport.authenticate('google', { scope: ['profile', 'email'] })
        );

        /**
         * GET /auth/google/callback
         * Handles Google OAuth callback.
         */
        app.get('/auth/google/callback',
            passport.authenticate('google', { session: false, failureRedirect: '/login' }),
            (req, res) => {
                const user = req.user;
                const token = jwt.sign(
                    { sub: user.id, email: user.email, role: 'user' },
                    CONFIG.JWT_SECRET,
                    { expiresIn: CONFIG.JWT_EXPIRES_IN }
                );
                publishEvent('UserLoggedIn', { userId: user.id, method: 'google' });
                // For SPA redirect can include token in query/hash or set cookie
                const redirectUrl = `${process.env.WEB_APP_URL || 'http://localhost:3000'}/social-login?token=${token}`;
                res.redirect(redirectUrl);
            });
    }

    /**
     * GET /auth/me
     * Returns details of authenticated user.
     */
    app.get('/auth/me',
        passport.authenticate('jwt', { session: false }),
        (req, res) => res.json({ user: { id: req.user.id, email: req.user.email, displayName: req.user.displayName } })
    );

    /**
     * POST /auth/logout
     * Stateless logout (emit event on client-side).
     */
    app.post('/auth/logout',
        passport.authenticate('jwt', { session: false }),
        (req, res) => {
            publishEvent('UserLoggedOut', { userId: req.user.id });
            res.status(204).end();
        }
    );

    /* ───────────── Error Handling ───────────── */
    // 404
    app.use((_req, res, _next) => res.status(404).json({ error: 'Not found' }));

    // Error-handler
    // eslint-disable-next-line no-unused-vars
    app.use((err, _req, res, _next) => {
        console.error(err);
        const status = err.status || 500;
        const message = CONFIG.NODE_ENV === 'production'
            ? (status === 500 ? 'Internal server error' : err.message)
            : err.stack;
        res.status(status).json({ error: message });
    });

    return app;
}

/* ──────────────────────────────────────────────────────────────────────────
 * Bootstrap – start server, connect DB, Kafka, graceful shutdown
 * ────────────────────────────────────────────────────────────────────────── */
(async () => {
    try {
        // Connect to PostgreSQL
        await sequelize.authenticate();
        await sequelize.sync(); // In production -> migrations
        console.log('[AuthService] Database connection established.');

        // Connect Kafka
        await producer.connect();
        console.log('[AuthService] Kafka producer connected.');

        // Start HTTP server
        const app    = buildApp();
        const server = http.createServer(app);

        server.listen(CONFIG.PORT, () => {
            console.log(`[AuthService] Listening on ${CONFIG.PORT} (${CONFIG.NODE_ENV})`);
        });

        /* Graceful Shutdown */
        const shutdown = async (signal) => {
            console.log(`\n[AuthService] Received ${signal}, shutting down...`);
            try {
                await producer.disconnect();
                await sequelize.close();
                server.close(() => {
                    console.log('[AuthService] HTTP server closed.');
                    process.exit(0);
                });
            } catch (err) {
                console.error('[AuthService] Error during shutdown', err);
                process.exit(1);
            }
        };
        process.on('SIGINT', () => shutdown('SIGINT'));
        process.on('SIGTERM', () => shutdown('SIGTERM'));

    } catch (err) {
        console.error('[AuthService] Failed to bootstrap service:', err);
        process.exit(1);
    }
})();
```