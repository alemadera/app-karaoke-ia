import streamlit as st
import subprocess
import os
import shutil
import tempfile
import time
from pathlib import Path
import soundfile as sf
import whisper
import imageio_ffmpeg as ffmpeg
import base64

# Función para ejecutar comandos de sistema
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

# Función para crear botón de descarga
def download_button(file_path, label="⬇️ Descargar video karaoke"):
    with open(file_path, "rb") as f:
        video_bytes = f.read()
        b64 = base64.b64encode(video_bytes).decode()
        href = f'<a href="data:video/mp4;base64,{b64}" download="video_karaoke.mp4">{label}</a>'
        st.markdown(href, unsafe_allow_html=True)

# Obtenemos ruta de ffmpeg
ffmpeg_exe = ffmpeg.get_ffmpeg_exe()

# Configuración de la app
st.set_page_config(page_title="Karaoke con IA", page_icon="🎤")
st.title("🎤 Creador de Karaoke con IA (Demucs + Whisper)")

st.markdown("""
Sube un video musical, y esta app usará IA para:
- Separar las voces del audio (Demucs)
- Generar subtítulos con inteligencia artificial (Whisper)
- Crear un video de karaoke para descargar
""")

st.warning("⚠️ El proceso puede tardar varios minutos. Sé paciente mientras se procesa el video.")

# Subida del archivo
uploaded_file = st.file_uploader("📁 Sube tu video (MP4, MKV, MOV, AVI, WEBM)", type=["mp4", "mkv", "mov", "avi", "webm"])

# Opciones
generate_lyrics = st.checkbox("🧠 Generar letras con IA (Whisper)", value=True)
selected_whisper_model = "medium" if generate_lyrics else None

# Procesamiento
if uploaded_file is not None:
    st.video(uploaded_file)

    if st.button("▶️ Iniciar procesamiento"):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            st.info("🚀 Procesando video, esto puede tardar. No cierres la ventana.")
            progress_bar = st.progress(0)
            status_text = st.empty()

            start_total = time.time()

            try:
                # Guardar video temporalmente
                video_path = tmpdir_path / uploaded_file.name
                with open(video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # 1. Extraer audio
                progress_bar.progress(10, "Extrayendo audio del video...")
                audio_path = tmpdir_path / "input_audio.wav"
                cmd = [
                    ffmpeg_exe, "-y", "-i", str(video_path), "-vn",
                    "-ac", "2", "-ar", "44100", "-acodec", "pcm_s16le", str(audio_path)
                ]
                run_command(cmd, show_output=False)
                status_text.text("✅ Audio extraído.")

                # 2. Separar voces con Demucs
                progress_bar.progress(30, "Separando voces con Demucs...")
                os.chdir(tmpdir)  # Demucs requiere estar en el directorio de trabajo
                run_command(["demucs", "--name", "htdemucs", "--two-stems", "vocals", str(audio_path)], show_output=False)

                voice_path = next(Path(tmpdir).glob("separated/*/input_audio/vocals.wav"), None)
                if not voice_path:
                    st.error("❌ Error: No se generó vocals.wav")
                    st.stop()

                # 3. Crear instrumental
                progress_bar.progress(60, "Creando pista instrumental...")
                instrumental_path = tmpdir_path / "instrumental.wav"
                a_mix, sr = sf.read(str(audio_path))
                a_voc, _ = sf.read(str(voice_path))
                min_len = min(len(a_mix), len(a_voc))
                a_inst = a_mix[:min_len] - a_voc[:min_len]
                sf.write(instrumental_path, a_inst, sr)
                status_text.text("✅ Pista instrumental creada.")

                # 4. Transcripción con Whisper
                srt_path = None
                if generate_lyrics:
                    progress_bar.progress(80, "Generando subtítulos con Whisper...")
                    model = whisper.load_model(selected_whisper_model)
                    result = model.transcribe(str(audio_path), word_timestamps=True, verbose=False, language="es")
                    srt_path = tmpdir_path / "lyrics.srt"
                    with open(srt_path, "w", encoding="utf-8") as srt_file:
                        for i, seg in enumerate(result["segments"]):
                            start, end = seg["start"], seg["end"]
                            text = seg["text"].strip()
                            srt_file.write(f"{i + 1}\n")
                            srt_file.write(f"{int(start//3600):02}:{int((start%3600)//60):02}:{int(start%60):02},{int((start%1)*1000):03} --> ")
                            srt_file.write(f"{int(end//3600):02}:{int((end%3600)//60):02}:{int(end%60):02},{int((end%1)*1000):03}\n")
                            srt_file.write(f"{text}\n\n")
                    status_text.text("✅ Subtítulos generados.")

                # 5. Reconstruir video
                progress_bar.progress(95, "Creando video karaoke final...")
                output_path = tmpdir_path / "video_karaoke.mp4"
                cmd = [
                    ffmpeg_exe, "-y", "-i", str(video_path), "-i", str(instrumental_path),
                    "-c:v", "libx264", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", "-shortest"
                ]
                if srt_path:
                    cmd += ["-vf", f"subtitles={str(srt_path)}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&HFFFFFF&'"]
                cmd += [str(output_path)]
                run_command(cmd, show_output=False)

                # Mostrar video y descarga
                if output_path.exists():
                    progress_bar.progress(100, "✅ Video listo")
                    st.success("🎉 Video karaoke creado exitosamente.")
                    st.video(str(output_path))
                    download_button(output_path)
                else:
                    st.error("❌ No se pudo crear el video final.")

                total_time = time.time() - start_total
                minutes = int(total_time // 60)
                seconds = int(total_time % 60)
                st.info(f"⏱️ Tiempo total: {minutes} min {seconds} seg")

            except Exception as e:
                st.error(f"❌ Error durante el procesamiento: {e}")
else:
    st.info("👈 Sube un video para comenzar.")
