#!/usr/bin/env python3
"""
Jarvis Voice Command Bridge.
Listens to the microphone via WhisperLiveKit server and sends commands
starting with 'jarvis' and ending with 'end command' to Claude Code.
"""
import asyncio
import sys
import json
import os
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage, ClaudeAgentOptions
try:
    import pyaudio
except ImportError:
    print("Error: pyaudio is not installed. Please install it with: pip install pyaudio")
    sys.exit(1)
try:
    import websockets
except ImportError:
    print("Error: websockets is not installed. Please install it with: pip install websockets")
    sys.exit(1)

# Audio configuration - must match WhisperLiveKit server
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK_DURATION = 0.1
CHUNK_SIZE = int(RATE * CHUNK_DURATION)

def generate_wav_header(sample_rate=16000, bits_per_sample=16, channels=1, data_size=0xFFFFFFFF):
    data_size = 0xFFFFFFFF - 36
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    header = bytearray()
    header.extend(b'RIFF')
    header.extend((36 + data_size).to_bytes(4, 'little'))
    header.extend(b'WAVE')
    header.extend(b'fmt ')
    header.extend((16).to_bytes(4, 'little'))
    header.extend((1).to_bytes(2, 'little'))
    header.extend(channels.to_bytes(2, 'little'))
    header.extend(sample_rate.to_bytes(4, 'little'))
    header.extend(byte_rate.to_bytes(4, 'little'))
    header.extend(block_align.to_bytes(2, 'little'))
    header.extend(bits_per_sample.to_bytes(2, 'little'))
    header.extend(b'data')
    header.extend(data_size.to_bytes(4, 'little'))
    return bytes(header)

async def send_to_claude(command, client):
    print(f"\n🚀 Sending to Claude: {command}")
    try:
        await client.query(command)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print("\nClaude Response to: ", command, ". \nis: ", block.text)
    except Exception as e:
        print(f"Failed to send command to Claude: {e}")

async def main():
    print("Connecting to WhisperLiveKit server at ws://localhost:8000/asr...")
    options = ClaudeAgentOptions(
        mcp_servers={
            "paraview_mcp": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "--name", "paraview_mcp", "paraview_mcp"],
                "env": {},
            }
        },
        allowed_tools=["mcp__paraview_mcp__*"]
    )

    async with ClaudeSDKClient(options=options) as client:    
        async with websockets.connect(
            "ws://localhost:8000/asr",
            ping_interval=20,
            ping_timeout=20
        ) as websocket:
            print("Connected. Listening for 'jarvis ... end command'...")
            
            config_raw = await websocket.recv()
            config_msg = json.loads(config_raw)
            use_pcm = config_msg.get("useAudioWorklet", False)
            
            # Shared state for decoupling
            state = {
                "latest_data": None,
                "capturing_command": False,
                "last_processed_end_index": -1
            }

            async def receiver():
                """Background task: Just keep the most recent message."""
                try:
                    async for raw_msg in websocket:
                        state["latest_data"] = raw_msg
                except Exception as e:
                    print(f"\nReceiver error: {e}")

            async def processor():
                """Background task: Process the most recent message every 1 second."""
                while True:
                    raw_msg = state["latest_data"]
                    if raw_msg:
                        try:
                            data = json.loads(raw_msg)
                            lines = data.get("lines", [])
                            buffer = data.get("buffer_transcription", "")
                            text_parts = [line["text"] for line in lines if line.get("text")]
                            full_text = " ".join(text_parts) + " " + buffer
                            lower_text = full_text.lower()

                            if not state["capturing_command"] and "jarvis" in lower_text:
                                state["capturing_command"] = True
                                print("\n🎙️ Jarvis listening...")

                            if state["capturing_command"]:
                                if "end command" in lower_text:
                                    last_jarvis_idx = lower_text.rfind("jarvis")
                                    first_end_idx = lower_text.find("end command", last_jarvis_idx)
                                    
                                    if first_end_idx != -1 and first_end_idx > state["last_processed_end_index"]:
                                        command = full_text[last_jarvis_idx + 6 : first_end_idx].strip()
                                        asyncio.create_task(send_to_claude(command, client))
                                        state["last_processed_end_index"] = first_end_idx
                                        state["capturing_command"] = False
                                        print("\n✅ Command processed. Listening again...")

                            if buffer:
                                print(f"\rListening... {buffer}", end="", flush=True)
                        except Exception as e:
                            print(f"Processing error: {e}")
                    
                    await asyncio.sleep(1) # ONLY check every 1 second

            # Start both background tasks
            recv_task = asyncio.create_task(receiver())
            proc_task = asyncio.create_task(processor())

            audio = pyaudio.PyAudio()
            stream = audio.open(
                format=FORMAT, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK_SIZE
            )
            
            if not use_pcm:
                await websocket.send(generate_wav_header())

            try:
                while True:
                    # We use loop.run_in_executor because stream.read is blocking
                    # This prevents the audio reading from freezing the websocket tasks
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, stream.read, CHUNK_SIZE, False
                    )
                    await websocket.send(data)
                    await asyncio.sleep(0) # Yield control to background tasks
            except KeyboardInterrupt:
                await websocket.send(b"")
            finally:
                stream.stop_stream()
                stream.close()
                audio.terminate()
                recv_task.cancel()
                proc_task.cancel()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
