import { useEffect, useRef } from 'react';
import { isTauri } from '@tauri-apps/api/core';
import { register, unregister } from '@tauri-apps/plugin-global-shortcut';
import { enable, isEnabled } from '@tauri-apps/plugin-autostart';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { ask } from '@tauri-apps/plugin-dialog';

export function useDesktopIntegration(toggleCall: () => void) {
  // Use a ref to ensure the callback is always fresh without re-running useEffect
  const toggleCallRef = useRef(toggleCall);
  
  useEffect(() => {
    toggleCallRef.current = toggleCall;
  }, [toggleCall]);

  useEffect(() => {
    let setupDone = false;

    const setupDesktop = async () => {
      if (!isTauri()) return;

      // 1. Global Shortcut
      try {
        await register('CommandOrControl+Space', (event: any) => {
          if (event.state === 'Pressed') {
            toggleCallRef.current();
          }
        });
      } catch (err) {
        console.error("Failed to register shortcut", err);
      }

      // 2. Autostart
      try {
        const autostartEnabled = await isEnabled();
        if (!autostartEnabled) {
          await enable();
        }
      } catch (err) {
        console.error("Failed to set autostart", err);
      }

      // 3. Window Close Dialog
      try {
        const appWindow = getCurrentWindow();
        await appWindow.onCloseRequested(async (event: any) => {
          // Prevent the default close behavior
          event.preventDefault();
          
          const answer = await ask('Deseja fechar o Jarvis completamente?\n\nClique em Minimizar para deixá-lo rodando no fundo (System Tray).', {
            title: 'Sair do Jarvis',
            kind: 'warning',
            okLabel: 'Fechar',
            cancelLabel: 'Minimizar'
          });
          
          if (answer) {
            // User wants to close completely
            await appWindow.destroy();
          } else {
            // User wants to minimize to tray
            await appWindow.hide();
          }
        });
      } catch (err) {
        console.error("Failed to set window close interceptor", err);
      }
      
      setupDone = true;
    };

    setupDesktop();

    return () => {
      if (setupDone) {
        unregister('CommandOrControl+Space').catch(console.error);
      }
    };
  }, []);
}
