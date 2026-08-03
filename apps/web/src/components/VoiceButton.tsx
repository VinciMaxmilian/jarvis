import React, { useEffect, useState, useCallback } from 'react';
import { useDesktopIntegration } from '../hooks/useDesktopIntegration';
import { useVoiceCall } from '../hooks/useVoiceCall';
import { useWakeWord } from '../hooks/useWakeWord';

const SphereOfDots = () => {
  const dots = Array.from({ length: 12 });
  
  return (
    <div style={{ position: 'relative', width: 120, height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      {dots.map((_, i) => {
        const angle = (i * 360) / dots.length;
        return (
          <div
            key={i}
            className="animate-pulse-ring"
            style={{
              position: 'absolute',
              width: 12,
              height: 12,
              background: 'var(--accent)',
              borderRadius: '50%',
              transform: `rotate(${angle}deg) translate(40px)`,
              animationDelay: `${i * 0.1}s`,
              animationDuration: '1.2s'
            }}
          />
        );
      })}
      <div className="animate-pulse-ring" style={{ position: 'absolute', width: 48, height: 48, background: 'var(--accent-glow)', borderRadius: '50%' }} />
    </div>
  );
};

export const VoiceButton: React.FC = () => {
  const { voiceState, startCall, endCall } = useVoiceCall();
  const [showModal, setShowModal] = useState(false);
  
  const toggleCall = useCallback(() => {
    if (voiceState === 'idle') {
      startCall();
    } else {
      endCall();
    }
  }, [voiceState, startCall, endCall]);
  
  useDesktopIntegration(toggleCall);

  const handleWakeWord = useCallback(() => {
    if (voiceState === 'idle') {
      startCall();
    }
  }, [voiceState, startCall]);

  const { isActive: wakeWordActive, toggleWakeWord } = useWakeWord(handleWakeWord);

  useEffect(() => {
    if (voiceState !== 'idle') {
      setShowModal(true);
    } else {
      setShowModal(false);
    }
  }, [voiceState]);

  return (
    <>
      {/* Voice Controls floating on bottom right */}
      <div style={{
        position: 'fixed',
        bottom: 90,
        right: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        zIndex: 50
      }}>
        {/* Wake Word Toggle */}
        <button
          onClick={toggleWakeWord}
          className="neu-btn"
          style={{
            padding: 12,
            borderRadius: '50%',
            background: wakeWordActive ? 'var(--neu-surface)' : 'var(--neu-surface)',
            color: wakeWordActive ? 'hsl(var(--neon-green))' : 'var(--ink-3)',
            boxShadow: wakeWordActive ? 'var(--neu-in-sm)' : 'var(--neu-sm)',
          }}
          title={wakeWordActive ? "Wake word active (Listening for 'Jarvis')" : "Enable wake word"}
        >
          {wakeWordActive ? (
            <svg style={{width: 24, height: 24}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
          ) : (
            <svg style={{width: 24, height: 24}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" /></svg>
          )}
        </button>

        {/* Main Call Button */}
        <button
          onClick={() => voiceState === 'idle' ? startCall() : endCall()}
          className="neu-btn"
          style={{
            padding: 16,
            borderRadius: '50%',
            background: voiceState === 'idle' ? 'linear-gradient(145deg, var(--accent-soft), var(--accent))' : 'hsl(var(--neon-red))',
            color: 'white',
            boxShadow: voiceState === 'idle' ? 'var(--neu-sm), 0 6px 16px var(--accent-glow)' : 'var(--neu-in-sm)',
            border: 'none'
          }}
        >
          {voiceState === 'idle' ? (
            <svg style={{width: 32, height: 32}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>
          ) : (
             <svg style={{width: 32, height: 32}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" /></svg>
          )}
        </button>
      </div>

      {/* Full screen modal for active call */}
      {showModal && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', 
          backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', 
          justifyContent: 'center', zIndex: 100
        }}>
          <div className="neu-flat" style={{
            padding: 32, display: 'flex', flexDirection: 'column', 
            alignItems: 'center', gap: 24, width: 320, background: 'var(--neu-bg)'
          }}>
            <h2 style={{ fontSize: 20, fontWeight: 500, color: 'var(--ink)' }}>
              {voiceState === 'connecting' && 'Conectando...'}
              {voiceState === 'listening' && 'Ouvindo...'}
              {voiceState === 'speaking' && 'Jarvis Falando'}
            </h2>
            
            <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {voiceState === 'speaking' ? (
                <SphereOfDots />
              ) : (
                <div className={voiceState === 'listening' ? 'animate-pulse-ring' : ''} style={{
                  width: 96, height: 96, borderRadius: '50%', background: 'var(--accent-glow)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                  <div style={{
                    width: 64, height: 64, borderRadius: '50%', background: 'var(--accent-glow)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center'
                  }}>
                    <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--accent)' }} />
                  </div>
                </div>
              )}
            </div>

            <button 
              onClick={endCall}
              className="neu-btn"
              style={{ marginTop: 16, color: 'hsl(var(--neon-red))' }}
            >
              Encerrar
            </button>
          </div>
        </div>
      )}
    </>
  );
};
