from pydub import AudioSegment
import requests
import io
import logging

logger = logging.getLogger(__name__)


def mix_voice_with_music(voice_file, output_file, music_url):
    """Миксует голосовое с музыкой и сохраняет в MP3"""

    # --- Загружаем голос (ogg/oga) ---
    voice = AudioSegment.from_file(voice_file, format="ogg")
    logger.info(f"🎤 Voice: {voice.duration_seconds:.2f}s, frames={len(voice)}")

    # --- Загружаем музыку ---
    resp = requests.get(music_url, timeout=60)
    resp.raise_for_status()
    music = AudioSegment.from_file(io.BytesIO(resp.content), format="mp3")
    logger.info(f"🎼 Music: {music.duration_seconds:.2f}s, frames={len(music)}")

    # --- Подгоняем музыку под голос ---
    if len(music) < len(voice):
        music = music * (len(voice) // len(music) + 1)  # зацикливаем
    music = music[:len(voice)]

    # --- Делаем фон тише ---
    music = music - 10

    # --- Миксуем ---
    mixed = music.overlay(voice)

    # --- Сохраняем ---
    mixed.export(output_file, format="mp3")
    logger.info(f"✅ Mixed saved: {output_file}, duration={mixed.duration_seconds:.2f}s, size={len(mixed)} frames")
