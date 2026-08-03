import { useState, useRef, useCallback } from 'react';
import { getApiBase } from '../config';

type VoiceState = 'idle' | 'connecting' | 'listening' | 'speaking';

export function useVoiceCall() {
  const [voiceState, setVoiceState] = useState<VoiceState>('idle');
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef(false);

  const playNextAudio = async () => {
    if (isPlayingRef.current || audioQueueRef.current.length === 0) return;
    
    isPlayingRef.current = true;
    setVoiceState('speaking');
    
    const base64Audio = audioQueueRef.current.shift();
    if (base64Audio) {
      try {
        const audioData = atob(base64Audio);
        const arrayBuffer = new ArrayBuffer(audioData.length);
        const view = new Uint8Array(arrayBuffer);
        for (let i = 0; i < audioData.length; i++) {
          view[i] = audioData.charCodeAt(i);
        }
        
        if (!audioContextRef.current) {
          audioContextRef.current = new AudioContext({ sampleRate: 24000 });
        }
        
        // Convert raw 16-bit PCM to Float32
        const int16Array = new Int16Array(arrayBuffer);
        const audioBuffer = audioContextRef.current.createBuffer(1, int16Array.length, 24000);
        const channelData = audioBuffer.getChannelData(0);
        for (let i = 0; i < int16Array.length; i++) {
          channelData[i] = int16Array[i] / 32768.0;
        }
        
        const source = audioContextRef.current.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioContextRef.current.destination);
        
        source.onended = () => {
          isPlayingRef.current = false;
          if (audioQueueRef.current.length > 0) {
            playNextAudio();
          } else {
            setVoiceState('listening');
          }
        };
        
        source.start();
      } catch (e) {
        console.error("Error playing audio chunk", e);
        isPlayingRef.current = false;
        setVoiceState('listening');
      }
    }
  };

  const startCall = useCallback(async () => {
    if (voiceState !== 'idle') return;
    
    setVoiceState('connecting');
    
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Seu navegador não suporta acesso ao microfone, ou você não está em um ambiente seguro (HTTPS/localhost).");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      const apiBase = getApiBase();
      let wsUrl = '';
      if (apiBase) {
        const wsBase = apiBase.replace(/^http/, 'ws');
        wsUrl = `${wsBase}/api/voice/call`;
      } else {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        wsUrl = `${protocol}//${window.location.host}/api/voice/call`;
      }
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onopen = () => {
        setVoiceState('listening');
        
        try {
          const audioCtx = new AudioContext({ sampleRate: 16000 });
          const source = audioCtx.createMediaStreamSource(stream);
          const processor = audioCtx.createScriptProcessor(4096, 1, 1);
          
          source.connect(processor);
          processor.connect(audioCtx.destination);
          
          if (audioCtx.state === 'suspended') {
            audioCtx.resume();
          }
          
          processor.onaudioprocess = (e) => {
            if (ws.readyState !== WebSocket.OPEN) return;
            const inputData = e.inputBuffer.getChannelData(0);
            const pcm16 = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
              pcm16[i] = Math.max(-32768, Math.min(32767, inputData[i] * 32768));
            }
            const buffer = new Uint8Array(pcm16.buffer);
            let binary = '';
            for (let i = 0; i < buffer.length; i++) {
              binary += String.fromCharCode(buffer[i]);
            }
            const base64data = btoa(binary);
            
            ws.send(JSON.stringify({
              type: 'realtime_input',
              media_chunks: [{
                mime_type: 'audio/pcm;rate=16000',
                data: base64data
              }]
            }));
          };
          
          // Save a reference so we can stop it later
          (ws as any)._audioCtx = audioCtx;
          (ws as any)._stream = stream;
        } catch (err) {
          console.error("Audio capture error:", err);
        }
      };
      
      ws.onmessage = (event) => {
        const payload = JSON.parse(event.data);
        if (payload.type === 'audio' && payload.data) {
          audioQueueRef.current.push(payload.data);
          playNextAudio();
        } else if (payload.type === 'call_ended_by_agent') {
          endCall();
        }
      };
      
      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        alert("Erro na conexão com o servidor de voz.");
        endCall();
      };
      
      ws.onclose = () => {
        endCall();
      };
      
    } catch (e: any) {
      console.error("Failed to start voice call", e);
      alert(`Falha ao iniciar chamada: ${e.message || e}`);
      setVoiceState('idle');
    }
  }, [voiceState]);

  const endCall = useCallback(() => {
    if (wsRef.current) {
      const ws = wsRef.current as any;
      if (ws._stream) {
        ws._stream.getTracks().forEach((t: any) => t.stop());
      }
      if (ws._audioCtx) {
        try { ws._audioCtx.close(); } catch(e) {}
      }
      try { ws.close(); } catch(e) {}
      wsRef.current = null;
    }
    
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch(e) {}
      audioContextRef.current = null;
    }
    
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    setVoiceState('idle');
  }, []);

  return {
    voiceState,
    startCall,
    endCall
  };
}
