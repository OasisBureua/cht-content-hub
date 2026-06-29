# services/lambdas/video/

Lambdas for the video / clip pipeline.

Note: transcription via Whisper API fits the 15-min Lambda ceiling. WhisperX (local GPU) does NOT fit Lambda — that path either drops with the EC2 retirement or runs on Fargate with GPU. Render jobs over 15 minutes also need Fargate.

Expected functions:

- `whisper_transcribe/` — Whisper API transcription, SQS-triggered
- `video_metadata_probe/` — FFprobe metadata extraction, fast
- `transcript_parser/` — pure utility, parses diarized transcript text

Out of scope for Lambda (needs Fargate):
- `render_engine` — multi-minute FFmpeg encoding
- `whisperx_transcribe` — GPU dependency; likely retired with EC2 box
