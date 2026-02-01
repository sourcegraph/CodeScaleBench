```javascript
/**
 *  PulseLearn Campus Hub – Course Service
 *  --------------------------------------
 *  uploadService.js
 *
 *  A centralized service responsible for handling file uploads
 *  (e.g., lecture slides, assignments, supplementary videos) to Amazon S3.
 *  The service abstracts bucket interactions, enforces file-size restrictions,
 *  emits domain events, and generates pre-signed URLs for secure downloads.
 *
 *  NOTE: All environment-specific values are read from process.env or an
 *  application-wide `config` module so that CI/CD pipelines (Docker/K8s)
 *  can inject secrets at runtime.
 */

'use strict';

const { Readable } = require('stream');
const { S3Client, PutObjectCommand, DeleteObjectCommand } = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');
const { v4: uuidv4 } = require('uuid');
const mime = require('mime-types');
const config = require('../config');           // application-wide configuration helper
const logger = require('../utils/logger');     // Winston-based logger wrapper
const eventBus = require('../events/eventBus'); // Domain-event publisher (Kafka/NATS abstraction)

const MAX_FILE_SIZE_BYTES = 1024 * 1024 * 250; // 250 MB – hard limit for an individual file
const DEFAULT_URL_EXPIRY   = 60 * 60;          // 1 hour (in seconds)

class UploadService {
  /**
   * Singleton instantiation – ensures that a single, shared S3 client is reused
   * across the micro-service’s lifetime to leverage connection pooling.
   */
  constructor() {
    const {
      AWS_S3_BUCKET_NAME: bucket,
      AWS_ACCESS_KEY_ID: accessKeyId,
      AWS_SECRET_ACCESS_KEY: secretAccessKey,
      AWS_REGION: region
    } = process.env;

    if (!bucket || !accessKeyId || !secretAccessKey || !region) {
      logger.error('AWS credentials or bucket information missing');
      throw new Error('UploadService initialization failure – missing AWS configuration');
    }

    this.bucketName = bucket;
    this.s3 = new S3Client({
      region,
      credentials: { accessKeyId, secretAccessKey }
    });
  }

  /* -------------------------------------------------------------------------- */
  /*                              Public API Methods                            */
  /* -------------------------------------------------------------------------- */

  /**
   * Upload a file stream/buffer to S3 and emit CourseMaterialUploaded event.
   *
   * @param {Object}  opts
   * @param {String}  opts.courseId    – Unique course identifier
   * @param {String}  opts.uploaderId  – The user (teacher/admin) uploading
   * @param {Buffer|Readable} opts.payload – File buffer or readable stream
   * @param {String}  opts.filename    – Original filename from client
   * @param {?String} opts.contentType – MIME type; autodetected if ommited
   *
   * @returns {Promise<{ key: string, url: string, size: number }>}
   */
  async uploadCourseMaterial({ courseId, uploaderId, payload, filename, contentType }) {
    const validated = await this.#preparePayload(payload, filename);
    if (validated.size > MAX_FILE_SIZE_BYTES) {
      throw new Error(`File size ${validated.size} exceeds ${MAX_FILE_SIZE_BYTES} bytes limit`);
    }

    const sanitizedFilename = this.#sanitizeFilename(filename);
    const extension = mime.extension(contentType) || mime.extension(validated.mime) || 'bin';

    // Object Key: course/{courseId}/{uuid}.{ext}
    const objectKey = [
      'course',
      courseId,
      `${uuidv4()}.${extension}`
    ].join('/');

    const putCommand = new PutObjectCommand({
      Bucket: this.bucketName,
      Key: objectKey,
      Body: validated.stream,
      ContentType: contentType || validated.mime,
      Metadata: {
        'uploaded-by': uploaderId,
        'original-filename': sanitizedFilename
      }
    });

    try {
      await this.s3.send(putCommand);

      // Emit domain event – downstream services (e.g., notification, analytics)
      await eventBus.publish('CourseMaterialUploaded', {
        courseId,
        uploaderId,
        objectKey,
        filename: sanitizedFilename,
        sizeBytes: validated.size,
        uploadedAt: new Date().toISOString()
      });

      const signedUrl = await this.generateSignedUrl(objectKey);

      logger.info(`File successfully uploaded to S3`, { courseId, objectKey });

      return {
        key: objectKey,
        url: signedUrl,
        size: validated.size
      };
    } catch (err) {
      logger.error('S3 upload failure', { err });
      throw new Error('File upload failed – please retry later');
    }
  }

  /**
   * Generate a pre-signed, time-limited download URL.
   *
   * @param {String} objectKey   – S3 object key
   * @param {Number} [expiry]    – TTL (in seconds) for the signed URL
   */
  async generateSignedUrl(objectKey, expiry = DEFAULT_URL_EXPIRY) {
    const cmd = new GetObjectCommand({
      Bucket: this.bucketName,
      Key: objectKey
    });

    try {
      return await getSignedUrl(this.s3, cmd, { expiresIn: expiry });
    } catch (err) {
      logger.error('Signed URL generation failed', { err });
      throw new Error('Unable to generate download link');
    }
  }

  /**
   * Delete a previously uploaded object from S3 and emit CourseMaterialDeleted.
   *
   * @param {String} opts.objectKey – S3 key to delete
   * @param {String} opts.requesterId – User who initiated deletion
   * @param {String} opts.courseId  – Associated course
   */
  async deleteCourseMaterial({ objectKey, requesterId, courseId }) {
    if (!objectKey) {
      throw new Error('objectKey is required for deletion');
    }

    try {
      await this.s3.send(
        new DeleteObjectCommand({
          Bucket: this.bucketName,
          Key: objectKey
        })
      );

      await eventBus.publish('CourseMaterialDeleted', {
        objectKey,
        courseId,
        requesterId,
        deletedAt: new Date().toISOString()
      });

      logger.info(`File deleted from S3`, { objectKey });
      return true;
    } catch (err) {
      logger.error('S3 deletion failure', { err });
      throw new Error('Unable to delete file');
    }
  }

  /* -------------------------------------------------------------------------- */
  /*                              Private Utilities                             */
  /* -------------------------------------------------------------------------- */

  /**
   *  Convert an incoming buffer/stream to a standardized readable stream.
   *  Also detects MIME type and accumulates size in bytes.
   *
   *  @param {Buffer|Readable} payload
   *  @param {String} filename
   *  @returns {Promise<{ stream: Readable, size: number, mime: string }>}
   */
  async #preparePayload(payload, filename) {
    if (!payload) {
      throw new Error('No file payload provided');
    }

    let byteLength;
    let stream;

    // Payload is already a stream
    if (payload instanceof Readable) {
      stream = payload;
      // We need to buffer to determine length for validation
      const chunks = [];
      for await (const chunk of payload) chunks.push(chunk);
      const buffer = Buffer.concat(chunks);
      byteLength = buffer.length;
      stream = Readable.from(buffer);
    } else if (Buffer.isBuffer(payload)) {
      byteLength = payload.length;
      stream = Readable.from(payload);
    } else {
      throw new TypeError('payload must be Buffer or Readable stream');
    }

    const mimeType =
      mime.lookup(filename) ||                      // Guess from filename
      (stream && stream.mime) ||                    // From library
      'application/octet-stream';

    return { stream, size: byteLength, mime: mimeType };
  }

  /**
   * Basic sanitization to avoid directory traversal and exotic characters.
   * @param {String} name
   * @returns {String} sanitized filename
   */
  #sanitizeFilename(name = '') {
    return name
      .replace(/[^a-zA-Z0-9.\-_]/g, '_') // whitelist‐based replacement
      .replace(/_+/g, '_')
      .substring(0, 100);                // enforce max length
  }
}

/* -------------------------------------------------------------------------- */
/*                               Export Singleton                             */
/* -------------------------------------------------------------------------- */

module.exports = new UploadService();
```