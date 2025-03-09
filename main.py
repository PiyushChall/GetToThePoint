from fastapi import FastAPI, Form, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled
from pydub import AudioSegment
from pydub.silence import split_on_silence
import speech_recognition as sr
from docx import Document
from dotenv import load_dotenv
import os
import re
import time

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

# --- Utility Functions ---

def get_youtube_transcript(video_id):
    try:
        # Fetch available transcript languages
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try to fetch transcript in any available language
        for transcript in transcript_list:
            try:
                # Fetch the transcript
                transcript_data = transcript.fetch()
                transcript_text = " ".join([item['text'] for item in transcript_data])
                return transcript_text
            except Exception as e:
                continue

        return "No transcript available in any language."

    except TranscriptsDisabled:
        return "Transcripts are disabled for this video."
    except Exception as e:
        return f"Error retrieving transcript: {e}"


def summarize_text(text):
    try:
        response = model.generate_content(f"Summarize the following text in a concise, point-wise format with bullet points:\n\n{text}\n use professional and clear tone and attractive words to maintain reader's engagement")
        return response.text
    except Exception as e:
        return f"Error summarizing text: {e}"

def extract_video_id(youtube_url):
    video_id_match = re.search(r"(?<=v=)[^&\s]+", youtube_url)
    if video_id_match:
        return video_id_match.group(0)
    else:
        return None

def extract_text_from_docx(docx_file):
    try:
        doc = Document(docx_file)
        text = []
        for paragraph in doc.paragraphs:
            text.append(paragraph.text)
        return '\n'.join(text)
    except Exception as e:
        return f"Error extracting text from docx: {e}"

# --- Audio Processing with Chunking ---

def transcribe_audio(audio_file, max_retries=3, retry_delay=5):
    recognizer = sr.Recognizer()

    # --- Split audio into chunks ---
    audio = AudioSegment.from_file(audio_file)
    chunks = split_on_silence(audio, min_silence_len=500, silence_thresh=-40)

    transcript = ""
    for i, chunk in enumerate(chunks):
        # Temporary file to store the chunk
        temp_chunk_file = f"temp_chunk_{i}.wav"
        chunk.export(temp_chunk_file, format="wav")

        with sr.AudioFile(temp_chunk_file) as source:
            audio_data = recognizer.record(source)

            for attempt in range(max_retries):
                try:
                    chunk_transcript = recognizer.recognize_google(audio_data)
                    transcript += f" {chunk_transcript}"
                    break  # Break out of retry loop if successful
                except sr.UnknownValueError:
                    transcript += " [Could not understand audio chunk] "
                    break
                except sr.RequestError as e:
                    if "Broken pipe" in str(e):
                        print(f"Retry attempt {attempt + 1} failed. Retrying in {retry_delay} seconds.")
                        time.sleep(retry_delay)
                    else:
                        transcript += f" [Could not transcribe audio chunk: {e}] "
                        break
            # Remove the temporary chunk file
            os.remove(temp_chunk_file)

    return transcript

# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/summarize")
async def summarize(request: Request,
                    youtube_url: str = Form(None),
                    text_input: str = Form(None),
                    audio_file: UploadFile = File(None),
                    docx_file: UploadFile = File(None)):

    summary = None
    error = None

    if youtube_url:
        video_id = extract_video_id(youtube_url)
        if video_id:
            transcript = get_youtube_transcript(video_id)
            if "Error" not in transcript:
                summary = summarize_text(transcript)
            else:
                error = transcript
        else:
            error = "Invalid YouTube URL"

    elif text_input  and not youtube_url or audio_file or docx_file:
        summary = summarize_text(text_input)

    elif audio_file and not youtube_url or text_input or docx_file:
        try:
            # Save the uploaded audio file temporarily
            with open("temp_audio.wav", "wb") as f:
                f.write(audio_file.file.read())
            transcript = transcribe_audio("temp_audio.wav")
            summary = summarize_text(transcript)
            os.remove("temp_audio.wav")  # Remove the temporary file
        except Exception as e:
            error = f"Error processing audio: {e}"

    elif docx_file and not youtube_url or text_input or audio_file:
        try:
            # Save the uploaded docx file temporarily
            with open("temp_doc.docx", "wb") as f:
                f.write(docx_file.file.read())
            text = extract_text_from_docx("temp_doc.docx")
            summary = summarize_text(text)
            os.remove("temp_doc.docx")  # Remove the temporary file
        except Exception as e:
            error = f"Error processing document: {e}"

    else:
        error = f"Error no input provided !"

    return templates.TemplateResponse("index.html", {"request": request, "summary": summary, "error": error})

'''
@app.post("/summarize")
async def summarize(
    text: str = Form(None),  # Text input from form
    file: UploadFile = File(None)  # File input from form
):
    if text and not file:
        # Process text input
        return {"summary": summarize_text(text)}

    elif file and not text:
        # Process file input
        if allowed_file(file.filename):
            return {"summary": process_file(file)}
        else:
            raise HTTPException(status_code=400, detail="Invalid file format.")

    elif not text and not file:
        raise HTTPException(status_code=400, detail="No input provided. Please enter text or upload a file.")

    else:
        raise HTTPException(status_code=400, detail="Provide only one input at a time (either text or file).")

def process_text(text: str):
    # Add text summarization logic here
    return f"Summarized text: {text[:50]}..."  # Example summary

def process_file(file: UploadFile):
    # Add file processing logic here
    return "Summarized file content"

def allowed_file(filename: str):
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'wav', 'mp3'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
'''

#To run "uvicorn main:app --reload"