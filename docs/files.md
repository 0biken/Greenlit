# Files

Uploads and downloads (TASKS M1-14, ARCH §5, SEC §6 and §8, PRD §9 "File types"). Code: `api/apps/files/`. Tests: `api/apps/files/tests/test_files.py`, plus the permission table and the isolation suite, which cover these routes automatically.

Only `apps.files` touches storage. Other modules store a file's ID and never a path.

## Flow

1. `POST /api/projects/{key}/files/` with `{kind, name, size}`. Needs the "write cases, record runs, attach evidence" right and a project you can see. Checks the kind, that the name is a type this kind accepts, the size limit and the organisation's quota. Returns the file record and an upload target valid for 15 minutes.
2. The browser sends the bytes to the target. The target is either `PUT` with the raw bytes and the given `Content-Type`, or `POST` as a multipart form with `fields` and the file last (S3). Storage enforces the size limit.
3. `POST /api/files/{id}/complete/` queues the `scan_file` job. It is safe to call twice.
4. The job checks the real size, identifies the content by its bytes, hashes it (SHA-256) and scans it for malware. Only then is the state `available`. A file whose content is not on the kind's list becomes `rejected`, and an infected file becomes `infected`; in both cases the stored bytes are deleted.
5. `GET /api/files/{id}/` to poll; `GET /api/files/{id}/download/` returns a link valid for 15 minutes. Before the file is available it answers 409.

An uploaded `prd` is queued for extraction only after the malware scan makes it available. PDF text
is stored with page and character offsets; DOCX, Markdown and plain-text content is stored with
character offsets. A successful extraction creates a source visible on the project's Sources API
and links it to the retained upload. Image-only PDFs and embedded images are not extracted yet; OCR
fallback is still open in M2-02. A file can therefore be available for download while its source
extraction job is still running or has failed.

Keys are `{org_id}/{project_id}/{uuid}`. Downloads are always attachments with `nosniff`, and never rendered inside the app.

## What each kind accepts

| Kind | Types | Limit |
| --- | --- | --- |
| `prd` | PDF, DOCX, Markdown, plain text | 20 MB |
| `screenshot` | PNG, JPEG, WebP | 20 MB |
| `qa_report` | PDF, DOCX | 20 MB |
| `evidence` | PNG, JPEG, WebP, GIF, MP4, WebM, MOV, PDF, plain text, JSON | 200 MB |

HTML and SVG are refused whatever they are called. A renamed file is judged by its content. The refusal message names the accepted types (UX §9), for example "This file type isn't supported here. Use PDF or DOCX."

The organisation quota is 10 GB on the starter plan (`ORG_STORAGE_QUOTA_BYTES`), counting pending, scanning and available files.

## Settings

| Variable | Development | Staging and production |
| --- | --- | --- |
| `FILE_STORAGE_BACKEND` | `local` (files in `api/var/files`) | `s3`; `manage.py check` refuses anything else (greenlit.E003) |
| `FILE_STORAGE_BUCKET`, `FILE_STORAGE_ENDPOINT`, `FILE_STORAGE_REGION`, `FILE_STORAGE_ACCESS_KEY`, `FILE_STORAGE_SECRET_KEY` | unused | the private bucket; links are signed with SigV4 |
| `MALWARE_SCANNER` | `stub` | `clamav`; `manage.py check` refuses the stub (greenlit.E002) |
| `CLAMAV_HOST`, `CLAMAV_PORT` | unused | the ClamAV daemon |

If ClamAV cannot be reached, the scan job retries and then waits in the dead-job list for an admin; the file is never released unscanned.

## Testing malware handling

The stub scanner flags the standard EICAR test file and Greenlit's own `TEST_MARKER` (`apps/files/scanner.py`). Desktop antivirus, including Windows Defender, quarantines EICAR as soon as it is written to disk. That is why the tests write the marker and check EICAR only in memory.

## Not yet proven

The S3 and ClamAV paths are tested only as far as can be done without the services: S3 links are signed and inspected locally, and an unreachable scanner is shown to hold files back. Neither has run against MinIO or ClamAV, which need Docker or a staging environment.
