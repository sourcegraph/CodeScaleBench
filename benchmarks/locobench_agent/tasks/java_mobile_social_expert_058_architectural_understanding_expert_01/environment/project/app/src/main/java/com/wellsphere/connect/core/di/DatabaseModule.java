package com.wellsphere.connect.core.di;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.datastore.preferences.preferencesDataStore;
import androidx.room.Room;
import androidx.room.RoomDatabase;

import com.wellsphere.connect.core.BuildConfig;
import com.wellsphere.connect.core.db.AppDatabase;
import com.wellsphere.connect.core.db.dao.MedicationDao;
import com.wellsphere.connect.core.db.dao.PatientDao;
import com.wellsphere.connect.core.db.dao.VitalDao;
import com.wellsphere.connect.core.db.migrations.DatabaseMigrations;
import com.wellsphere.connect.core.security.KeyStoreManager;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

import javax.crypto.SecretKey;
import javax.inject.Singleton;

import dagger.Module;
import dagger.Provides;
import dagger.hilt.InstallIn;
import dagger.hilt.android.qualifiers.ApplicationContext;
import dagger.hilt.components.SingletonComponent;
import net.sqlcipher.database.SQLiteDatabase;
import net.sqlcipher.database.SupportFactory;

/**
 * DI module responsible for providing database‐related singletons at application scope.
 *
 * <p>The module creates an encrypted Room database backed by SQLCipher. The encryption key
 * is generated on the device’s hardware‐backed keystore and persisted in {@link KeyStoreManager}.
 * All DAO instances are scoped as singletons to avoid redundant connection pooling.</p>
 *
 * <p>Because WellSphere Connect is a HIPAA‐aware application, PHI must be encrypted at rest.
 * Any failure in provisioning the encryption key is treated as fatal because the application
 * cannot continue without a secure database.</p>
 */
@Module
@InstallIn(SingletonComponent.class)
public final class DatabaseModule {

    private DatabaseModule() {
        // No instances.
    }

    /**
     * Provides the encryption key used by SQLCipher. If the key does not exist yet, it will be
     * generated once and stored in the Android Keystore.
     */
    @Provides
    @Singleton
    static byte[] provideDatabasePassphrase(@ApplicationContext @NonNull Context context) {
        try {
            final KeyStoreManager keyStoreManager = KeyStoreManager.getInstance(context);
            SecretKey secretKey = keyStoreManager.getOrCreateDatabaseKey();
            return secretKey.getEncoded();
        } catch (Exception e) {
            // We deliberately crash the app because running without encryption is not allowed.
            throw new IllegalStateException("Unable to load database encryption key.", e);
        }
    }

    /**
     * Provides the encrypted Room database instance.
     */
    @Provides
    @Singleton
    static AppDatabase provideAppDatabase(
            @ApplicationContext @NonNull Context context,
            @NonNull byte[] databasePassphrase) {

        // Initialise SQLCipher (required before building the database).
        SQLiteDatabase.loadLibs(context);

        SupportFactory factory = new SupportFactory(databasePassphrase);

        RoomDatabase.Builder<AppDatabase> builder = Room.databaseBuilder(
                        context,
                        AppDatabase.class,
                        BuildConfig.DB_NAME)
                .openHelperFactory(factory)
                // Run potentially long migrations on a background thread.
                .setQueryExecutor(Executors.newSingleThreadExecutor())
                .addMigrations(DatabaseMigrations.MIGRATION_1_2,
                               DatabaseMigrations.MIGRATION_2_3,
                               DatabaseMigrations.MIGRATION_3_4);

        if (BuildConfig.DEBUG) {
            // Allow main thread queries only in debug builds to aid tests/tools like Stetho.
            builder.allowMainThreadQueries();
        }

        return builder.build();
    }

    /* ------------------------------------------------------------------------
     * DAO Providers
     * --------------------------------------------------------------------- */

    @Provides
    @Singleton
    static PatientDao providePatientDao(@NonNull AppDatabase database) {
        return database.patientDao();
    }

    @Provides
    @Singleton
    static VitalDao provideVitalDao(@NonNull AppDatabase database) {
        return database.vitalDao();
    }

    @Provides
    @Singleton
    static MedicationDao provideMedicationDao(@NonNull AppDatabase database) {
        return database.medicationDao();
    }

    /* ------------------------------------------------------------------------
     * Preference DataStore (non‐PHI, e.g., feature flags) Providers
     * --------------------------------------------------------------------- */

    private static final String PREF_FILE_LEGACY = "wellsphere_prefs";
    private static final String PREF_MIGRATION_COMPLETE = "pref_migration_complete";

    @Provides
    @Singleton
    static SharedPreferences provideLegacySharedPreferences(
            @ApplicationContext @NonNull Context context) {

        return context.getSharedPreferences(PREF_FILE_LEGACY, Context.MODE_PRIVATE);
    }

    /**
     * On first run after DataStore migration, we ensure existing preferences have been migrated.
     * This method is intentionally synchronous because it executes only once and must finish
     * before any preference access to avoid inconsistent state.
     */
    @Provides
    @Singleton
    static androidx.datastore.core.DataStore<androidx.datastore.preferences.core.Preferences>
    providePreferencesDataStore(
            @ApplicationContext @NonNull Context context,
            @NonNull SharedPreferences legacyPrefs) {

        androidx.datastore.core.DataStore<androidx.datastore.preferences.core.Preferences> dataStore =
                preferencesDataStore(name = "wellsphere_settings").getValue(context, androidx.datastore.preferences.core.Preferences.Companion);

        boolean migrationDone = legacyPrefs.getBoolean(PREF_MIGRATION_COMPLETE, false);
        if (!migrationDone) {
            migrateLegacyPreferences(legacyPrefs, dataStore);
            legacyPrefs.edit().putBoolean(PREF_MIGRATION_COMPLETE, true).apply();
        }
        return dataStore;
    }

    /**
     * Migrates selected keys from SharedPreferences to DataStore.
     */
    private static void migrateLegacyPreferences(
            @NonNull SharedPreferences legacyPrefs,
            @NonNull androidx.datastore.core.DataStore<androidx.datastore.preferences.core.Preferences> dataStore) {

        // Only migrate non‐sensitive toggles / feature flags (PHI should be in the encrypted DB).
        final String KEY_CRASH_REPORTING = "crash_reporting_enabled";
        final String KEY_BIOMETRIC_AUTH = "biometric_auth_enabled";

        boolean crashReporting = legacyPrefs.getBoolean(KEY_CRASH_REPORTING, true);
        boolean biometricAuth = legacyPrefs.getBoolean(KEY_BIOMETRIC_AUTH, false);

        androidx.datastore.preferences.core.Preferences.Key<Boolean> crashKey =
                androidx.datastore.preferences.core.BooleanPreferencesKey(KEY_CRASH_REPORTING);
        androidx.datastore.preferences.core.Preferences.Key<Boolean> biomKey =
                androidx.datastore.preferences.core.BooleanPreferencesKey(KEY_BIOMETRIC_AUTH);

        try {
            dataStore.updateDataAsync(prefs -> {
                androidx.datastore.preferences.core.MutablePreferences mutable = prefs.toMutablePreferences();
                mutable.set(crashKey, crashReporting);
                mutable.set(biomKey, biometricAuth);
                return java.util.concurrent.CompletableFuture.completedFuture(mutable);
            });
        } catch (Exception e) {
            // If migration fails we log and continue; default values will be used.
            // Avoid crashing to not block user access.
            android.util.Log.e("DatabaseModule", "Preference migration failed", e);
        }
    }
}