import streamlit as st
import subprocess
import os
import shutil
import time
from pathlib import Path
import soundfile as sf
import whisper
import imageio_ffmpeg as ffmpeg  # Importamos imageio-ffmpeg para ffmpeg_exe

# --- Funciones Auxiliares ---

def run_command(cmd_list, show_output=True):
    process = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = ""
    for line in iter(process.stdout.readline, ""):
        if show_output:
            st.code(line.strip(), language='bash')
        output += line
    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"Error al ejecutar '{' '.join(cmd_list)}'\nCódigo de salida: {process.returncode}\nSalida:\n{output}")
    return output

# Obtenemos la ruta del ejecutable ffmpeg que provee imageio-ffmpeg
ffmpeg_exe = ffmpeg.get_ffmpeg_exe()

# --- Configuración de la aplicación Streamlit ---

st.set_page_config(
    page_title="Extractor de Instrumental y Creador de Karaoke (IA)",
    page_icon="🎤",
    layout="centered"
)

st.title("🎤 Extractor de Instrumental y Creador de Karaoke con IA")
st.markdown("""
Esta aplicación te permite **quitar las voces de un video** usando **Demucs**
y, opcionalmente, **generar las letras automáticamente con IA (Whisper)**
para crear un video de karaoke completo.
""")

st.warning("⚠️ **Importante:** El procesamiento puede tardar varios minutos. La separación de voces y la generación de letras consumen recursos (CPU) y el proceso de añadir letras al video requiere **recodificación**, lo cual es lento. Los resultados de la IA pueden variar en calidad.")

# Limpieza inicial de archivos y carpetas previas
for f in ["input_audio.wav", "instrumental.wav", "video_karaoke.mp4", "temp_lyrics.srt"]:
    if os.path.exists(f):
        os.remove(f)
if os.path.exists("separated"):
    shutil.rmtree("separated")

# --- 1) Subir video ---
st.header("1. Sube tu Video")
uploaded_file = st.file_uploader("Arrastra y suelta tu archivo de video aquí (MP4, MKV, MOV...)", type=["mp4", "mkv", "mov", "avi", "webm"])

# --- Opciones adicionales ---
st.header("2. Opciones de Procesamiento")
generate_lyrics = st.checkbox("Generar letras automáticamente con IA (Whisper)", value=True,
                              help="Si marcas esta opción, la IA transcribirá el audio y generará los subtítulos. Esto añade tiempo al proceso.")
selected_whisper_model = None
if generate_lyrics:
    st.info("Para un rendimiento razonable en CPU, se usará el modelo 'base' de Whisper.")
    selected_whisper_model = "large"  # Modelo por defecto para CPU

if uploaded_file is not None:
    st.video(uploaded_file, format=uploaded_file.type)
    video_path = Path(uploaded_file.name)

    # Guardar archivo subido localmente
    with open(video_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    st.success(f"✅ Video subido: `{video_path.name}`")

    if st.button("▶️ Iniciar Procesamiento"):
        st.info("Comenzando el procesamiento. ¡Sé paciente! ⏳")

        progress_bar = st.progress(0, text="Iniciando...")
        status_text = st.empty()

        start_total_time = time.time()

        try:
            progress_bar.progress(0, text="Iniciando proceso...")
            status_text.text("Estado: Iniciando proceso...")

            # --- Extracción de audio ---
            start_time_step = time.time()
            progress_bar.progress(10, text="Extrayendo audio del video...")
            status_text.text("Estado: Extrayendo audio del video...")
            audio_path = "input_audio.wav"

            cmd = [
                ffmpeg_exe,
                "-y",
                "-i", str(video_path),
                "-vn",
                "-ac", "2",
                "-ar", "44100",
                "-acodec", "pcm_s16le",
                audio_path
            ]
            with st.spinner("Extrayendo audio..."):
                run_command(cmd, show_output=False)

            if not os.path.exists(audio_path):
                st.error("❌ No se pudo extraer el audio del video.")
                st.stop()
            st.success(f"🎧 Audio extraído correctamente. (Tiempo: {time.time() - start_time_step:.2f} segundos)")

            # --- Demucs ---
            start_time_step = time.time()
            progress_bar.progress(30, text="Separando voces con Demucs...")
            status_text.text("Estado: Separando voces con Demucs...")
            demucs_output_dir = "separated"
            if os.path.exists(demucs_output_dir):
                shutil.rmtree(demucs_output_dir)

            with st.spinner("Demucs está procesando el audio para separar las voces. Esto puede tardar bastante..."):
                run_command(["demucs","--name", "htdemucs", "--two-stems", "vocals", audio_path], show_output=False)
            st.success(f"🎚️ Voces separadas por Demucs. (Tiempo: {time.time() - start_time_step:.2f} segundos)")

            voice_path = None
            for p in Path(demucs_output_dir).glob("*/input_audio/vocals.wav"):
                voice_path = p
                break

            if not voice_path or not voice_path.exists():
                st.error("❌ Demucs no pudo generar la pista de voces (vocals.wav).")
                st.stop()
            st.info(f"Pista de voces encontrada en: `{voice_path}`")

            # --- Crear instrumental ---
            start_time_step = time.time()
            progress_bar.progress(60, text="Calculando la pista instrumental...")
            status_text.text("Estado: Calculando la pista instrumental...")
            instrumental_audio_path = "instrumental.wav"
            with st.spinner("Calculando instrumental..."):
                a_mix, sr = sf.read(audio_path)
                a_voc, _ = sf.read(str(voice_path))

                min_len = min(len(a_mix), len(a_voc))
                a_mix = a_mix[:min_len]
                a_voc = a_voc[:min_len]

                a_inst = a_mix - a_voc
                sf.write(instrumental_audio_path, a_inst, sr)
            st.success(f"🎵 instrumental.wav creado. (Tiempo: {time.time() - start_time_step:.2f} segundos)")

            # --- Generar letras con Whisper (opcional) ---
            srt_path = None
            if generate_lyrics and selected_whisper_model:
                start_time_step = time.time()
                progress_bar.progress(80, text="Generando letras con IA (Whisper)...")
                status_text.text("Estado: Generando letras con IA (Whisper)...")
                srt_path = Path("temp_lyrics.srt")
                try:
                    with st.spinner(f"Cargando modelo '{selected_whisper_model}' de Whisper (puede tardar)..."):
                        model = whisper.load_model(selected_whisper_model)
                    st.success(f"✅ Modelo '{selected_whisper_model}' cargado.")

                    with st.spinner("Transcribiendo audio y generando archivo SRT..."):
                        result = model.transcribe(str(audio_path), word_timestamps=True, verbose=False, language="es")
                        with open(srt_path, "w", encoding="utf-8") as srt_file:
                            for i, segment in enumerate(result["segments"]):
                                start_time = segment["start"]
                                end_time = segment["end"]
                                text = segment["text"].strip()

                                srt_file.write(f"{i + 1}\n")
                                srt_file.write(f"{int(start_time // 3600):02}:{int((start_time % 3600) // 60):02}:{int(start_time % 60):02},{int((start_time % 1) * 1000):03} --> ")
                                srt_file.write(f"{int(end_time // 3600):02}:{int((end_time % 3600) // 60):02}:{int(end_time % 60):02},{int((end_time % 1) * 1000):03}\n")
                                srt_file.write(f"{text}\n\n")
                    st.success(f"📝 Archivo SRT generado exitosamente por Whisper. (Tiempo: {time.time() - start_time_step:.2f} segundos)")
                except Exception as e:
                    st.error(f"❌ Error al generar letras con Whisper: {e}. Se procederá sin letras.")
                    srt_path = None

            # --- Reconstruir video (con o sin letras) ---
            start_time_step = time.time()
            progress_bar.progress(95, text="Reconstruyendo video final...")
            status_text.text("Estado: Reconstruyendo video final...")
            output_video_path = "video_karaoke.mp4"

            cmd = [
                ffmpeg_exe,
                "-y",
                "-i", str(video_path),           # Video original
                "-i", instrumental_audio_path,   # Audio instrumental
            ]

            if srt_path and srt_path.exists():
                cmd += [
                    "-vf", f"subtitles={str(srt_path)}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&HFFFFFF&'",
                ]

            cmd += [
                "-c:v", "libx264",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                output_video_path
            ]

            with st.spinner("Renderizando video final, por favor espera..."):
                run_command(cmd, show_output=False)

            if os.path.exists(output_video_path):
                st.success(f"🎉 Video karaoke creado exitosamente en `{output_video_path}` (Tiempo: {time.time() - start_time_step:.2f} segundos)")
                st.video(output_video_path)
            else:
                st.error("❌ Error al crear el video karaoke final.")

            progress_bar.progress(100, text="Proceso completado")
            total_time = time.time() - start_total_time
            st.info(f"Proceso finalizado en {total_time:.2f} segundos.")

        except Exception as e:
            st.error(f"❌ Error durante el procesamiento: {e}")
            progress_bar.progress(0)
            status_text.text("")


