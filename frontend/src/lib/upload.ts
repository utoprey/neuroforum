import { api } from './api'
import { guessKind, humanizeBytes } from './attachments-limits'
import type {
  AttachmentKindLimits,
  AttachmentRead,
  AttachmentUploadResponse,
} from './types'

export interface UploadResult {
  attachment_id: string
  url: string
  width?: number
  height?: number
}

export class UploadValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'UploadValidationError'
  }
}

/**
 * Read width/height of an image File so we can attach the metadata to the
 * finalize request. Resolves to `null` for non-image kinds or on failure.
 */
async function probeImageDimensions(
  file: File,
): Promise<{ width: number; height: number } | null> {
  if (!file.type.startsWith('image/')) return null
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve({ width: img.naturalWidth, height: img.naturalHeight })
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(null)
    }
    img.src = url
  })
}

export interface UploadAttachmentOptions {
  /**
   * Optional pre-fetched limits map (e.g. from `useAttachmentLimits`). When
   * provided we run client-side validation before requesting a presigned URL.
   */
  limits?: Map<string, AttachmentKindLimits>
}

/**
 * Three-step MinIO upload helper:
 *   1. POST `/attachments/upload-url` — server registers the upcoming object
 *      and returns a presigned PUT URL.
 *   2. PUT the bytes to MinIO directly (NOT through the ky base — external URL).
 *   3. POST `/attachments/{id}/finalize` — mark the upload complete and grab
 *      the public URL.
 */
export async function uploadAttachment(
  file: File,
  options: UploadAttachmentOptions = {},
): Promise<UploadResult> {
  const kind = guessKind(file.type)
  const limit = options.limits?.get(kind)

  if (limit) {
    if (file.size > limit.max_bytes) {
      throw new UploadValidationError(
        `Файл больше ${limit.max_mb} МБ — лимит для типа «${kind}». Размер: ${humanizeBytes(file.size)}.`,
      )
    }
    if (
      limit.allowed_mime_types.length > 0 &&
      !limit.allowed_mime_types.includes(file.type)
    ) {
      throw new UploadValidationError(
        `Тип файла не поддерживается (${file.type}). Разрешено: ${limit.allowed_mime_types.join(', ')}.`,
      )
    }
  }

  const dims = await probeImageDimensions(file)

  // 1. Reserve attachment row + grab presigned PUT URL.
  const presign = await api
    .post('attachments/upload-url', {
      json: {
        filename: file.name,
        mime_type: file.type || 'application/octet-stream',
        size_bytes: file.size,
        kind,
      },
    })
    .json<AttachmentUploadResponse>()

  // 2. Upload bytes directly to MinIO. `fetch` deliberately, bypassing the
  //    ky base (presigned URL is fully external and signed with its own headers).
  const putResp = await fetch(presign.upload_url, {
    method: presign.upload_method || 'PUT',
    headers: presign.headers,
    body: file,
  })
  if (!putResp.ok) {
    throw new Error(
      `Загрузка в хранилище не удалась (HTTP ${putResp.status}). Попробуйте ещё раз.`,
    )
  }

  // 3. Finalize — backend marks the row as ready and returns the canonical URL.
  const finalized = await api
    .post(`attachments/${presign.attachment_id}/finalize`, {
      json: {
        ...(dims ? { width: dims.width, height: dims.height } : {}),
      },
    })
    .json<AttachmentRead>()

  return {
    attachment_id: finalized.id,
    url: finalized.url,
    width: finalized.width ?? dims?.width,
    height: finalized.height ?? dims?.height,
  }
}

/**
 * For seed-data attachments that point at picsum.photos through an
 * `external` bucket: rewrite the fake MinIO URL into a real picsum URL so
 * the editor still shows something useful in dev.
 */
export function resolveImageSrc(src: string | undefined | null): string {
  if (!src) return ''
  // External MinIO bucket pattern produced by the seed script.
  const m = src.match(/external\/picsum\/([^/]+)\/(\d+)\/(\d+)/)
  if (m) {
    const [, seed, w, h] = m
    return `https://picsum.photos/seed/${seed}/${w}/${h}`
  }
  return src
}
