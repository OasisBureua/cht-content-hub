# services/lambdas/video/

Video and clip pipeline Lambdas.

## Status

**Deferred to post-R1.** Per the migration plan, transcription and video processing move to SQS + Lambda/Fargate after Round 1 dev exit. Render stays on the existing EC2 GPU box until post-MVP, then migrates to ECS GPU + S3.

## Expected functions (when R1+ work begins)

- `whisper_transcribe/` — Whisper API transcription, SQS-triggered. Fits Lambda 15-min ceiling.
- `video_metadata_probe/` — FFprobe metadata extraction. Fast.
- `transcript_parser/` — pure utility, parses diarized transcript text.

## Out of scope for Lambda (needs Fargate)

- `render_engine` — multi-minute FFmpeg encoding. ECS GPU + S3, post-MVP.
- `whisperx_transcribe` — GPU dependency. Drops with the EC2 retirement unless explicitly kept.
- `auto_segmenter` — zero callers, retired.
