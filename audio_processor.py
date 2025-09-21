import os
import requests
import subprocess
import tempfile

def download_background_music(github_raw_url, local_filename):
    """Скачивает фоновую музыку из GitHub"""
    response = requests.get(github_raw_url, timeout=60)
    response.raise_for_status()
    with open(local_filename, 'wb') as f:
        f.write(response.content)
    return local_filename

def get_audio_duration(file_path):
    """Получает длительность аудиофайла в миллисекундах"""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration_seconds = float(result.stdout.strip())
    return int(duration_seconds * 1000)

def run_ffmpeg(cmd):
    """Запуск ffmpeg с логом ошибок"""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr}")
    return result

def mix_voice_with_music(voice_file_path, output_path, github_music_url):
    """
    Микширует голос с музыкой:
    - конвертирует voice в WAV
    - загружает и подрезает музыку
    - создаёт паузы в начале/конце
    - concat (пауза + голос + пауза)
    - накладывает музыку с fade in/out
    - сохраняет итог в MP3
    """
    start_pause_sec = 1.0
    end_pause_sec = 2.0
    fade_sec = 1.5

    temp_files = []

    try:
        # === Конвертируем голос в WAV ===
        voice_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        run_ffmpeg(["ffmpeg", "-y", "-i", voice_file_path, "-ar", "44100", "-ac", "2", voice_wav])
        temp_files.append(voice_wav)

        voice_duration = get_audio_duration(voice_wav)

        # === Скачиваем музыку ===
        bg_music_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
        download_background_music(github_music_url, bg_music_mp3)
        temp_files.append(bg_music_mp3)

        required_music_length = (voice_duration / 1000.0) + start_pause_sec + end_pause_sec
        music_duration = get_audio_duration(bg_music_mp3) / 1000.0

        # === Делаем музыку нужной длины ===
        music_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        if music_duration < required_music_length:
            loop_count = int(required_music_length // music_duration) + 2
            run_ffmpeg([
                "ffmpeg", "-y",
                "-stream_loop", str(loop_count),
                "-i", bg_music_mp3,
                "-ar", "44100", "-ac", "2",
                "-t", f"{required_music_length:.2f}",
                music_wav
            ])
        else:
            run_ffmpeg([
                "ffmpeg", "-y",
                "-i", bg_music_mp3,
                "-ar", "44100", "-ac", "2",
                "-t", f"{required_music_length:.2f}",
                music_wav
            ])
        temp_files.append(music_wav)

        # === Добавляем fade in/out ===
        music_faded_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", music_wav,
            "-af", f"afade=t=in:st=0:d={fade_sec},afade=t=out:st={required_music_length - fade_sec}:d={fade_sec}",
            music_faded_wav
        ])
        temp_files.append(music_faded_wav)

        # === Паузы (WAV) ===
        silence_start_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={start_pause_sec}",
            silence_start_wav
        ])
        temp_files.append(silence_start_wav)

        silence_end_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={end_pause_sec}",
            silence_end_wav
        ])
        temp_files.append(silence_end_wav)

        # === Собираем дорожку (пауза + голос + пауза) ===
        final_voice_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", silence_start_wav,
            "-i", voice_wav,
            "-i", silence_end_wav,
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1",
            final_voice_wav
        ])
        temp_files.append(final_voice_wav)

        # === Миксуем голос с музыкой ===
        final_mix_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", final_voice_wav,
            "-i", music_faded_wav,
            "-filter_complex", "[0:a]volume=1.0[voice];[1:a]volume=0.3[music];[voice][music]amix=inputs=2:duration=first:dropout_transition=2",
            final_mix_wav
        ])
        temp_files.append(final_mix_wav)

        # === Экспорт в MP3 ===
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", final_mix_wav,
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            output_path
        ])

        return output_path

    finally:
        for f in temp_files:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass
