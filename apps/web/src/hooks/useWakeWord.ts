import { useState, useEffect, useCallback, useRef } from 'react';

// Extend Window interface for standard and webkit prefixed SpeechRecognition
declare global {
  interface Window {
    SpeechRecognition: any;
    webkitSpeechRecognition: any;
  }
}

export function useWakeWord(onWakeWord: () => void) {
  const [isActive, setIsActive] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const recognitionRef = useRef<any>(null);

  const initRecognition = useCallback(() => {
    if (typeof window === 'undefined') return null;
    
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      return null; // Return null early without calling setState here
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'pt-BR'; // Adjust language if needed, e.g. en-US

    recognition.onresult = (event: any) => {
      const current = event.resultIndex;
      const transcript = event.results[current][0].transcript.toLowerCase();
      
      if (transcript.includes('jarvis')) {
        console.log('Wake word detected via Web Speech API!');
        onWakeWord();
      }
    };

    recognition.onerror = (event: any) => {
      // "no-speech" is common and not really a fatal error, just silence
      if (event.error !== 'no-speech') {
        console.error("Speech Recognition Error:", event.error);
      }
    };

    // Auto-restart to keep listening
    recognition.onend = () => {
      if (isActive) {
        try {
          recognition.start();
        } catch (e) {
          // ignore already started errors
        }
      }
    };

    return recognition;
  }, [isActive, onWakeWord]);

  useEffect(() => {
    if (isActive) {
      if (!recognitionRef.current) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
           setError(new Error("Seu navegador não suporta a Web Speech API. Tente no Chrome."));
           setIsActive(false); // Turn off to prevent loop
           return;
        }
        recognitionRef.current = initRecognition();
      }
      
      try {
        recognitionRef.current?.start();
      } catch (e) {
        // ignore already started errors
      }
    } else {
      if (recognitionRef.current) {
        try {
          recognitionRef.current.stop();
        } catch(e) {}
      }
    }

    return () => {
      if (recognitionRef.current) {
        try {
           recognitionRef.current.stop();
        } catch(e) {}
      }
    };
  }, [isActive, initRecognition]);

  const toggleWakeWord = () => {
    setIsActive(prev => !prev);
  };

  return {
    isActive,
    toggleWakeWord,
    error,
    isLoaded: true // Always true for native API
  };
}
