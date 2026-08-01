/**
 * Configurações do sistema — `apps/api/routers/settings.py`.
 *
 * Os três endpoints respondem perguntas distintas e o router é explícito sobre
 * por quê: `/providers` é "o que posso escolher" (mapa em memória, nunca falha),
 * `/profiles` é "o que está servindo agora" (pergunta ao provider, pode falhar
 * ou demorar) e `/` é o que está persistido. A tela reproduz essa separação —
 * `/profiles` cair não pode impedir de trocar de provider.
 */

import { api } from './client';

export interface ProviderOption {
  id: string;
  default_model: string;
}

export interface ProviderCatalog {
  providers: ProviderOption[];
}

export interface ProfileAssignment {
  profile: string;
  model: string;
  source: string;
  degraded: boolean;
  reason: string;
}

export interface ProfileCatalog {
  provider: string;
  /**
   * `false` = não deu para perguntar ao provider o que ele serve. A resolução
   * continua válida (é a mesma que as gerações usam), mas não foi verificada, e
   * a tela precisa poder dizer isso em vez de exibir uma certeza que não existe.
   */
  roster_available: boolean;
  fallback_model: string;
  profiles: ProfileAssignment[];
}

/** `SystemSettings` de `packages/shared/contracts.py`. */
export interface SystemSettings {
  provider: string;
  model: string;
  temperature: number;
  system_prompt: string;
}

/** `GET /api/settings/providers` */
export async function listProviders(): Promise<ProviderCatalog> {
  const { data } = await api.get<ProviderCatalog>('/api/settings/providers');
  return data;
}

/** `GET /api/settings/profiles` */
export async function listProfiles(): Promise<ProfileCatalog> {
  const { data } = await api.get<ProfileCatalog>('/api/settings/profiles');
  return data;
}

/** `GET /api/settings/` */
export async function getSystemSettings(): Promise<SystemSettings> {
  const { data } = await api.get<SystemSettings>('/api/settings/');
  return data;
}

/**
 * `PUT /api/settings/`.
 *
 * Manda o objeto inteiro porque a rota é PUT, não PATCH: omitir um campo o
 * substitui pelo default do pydantic, não o preserva.
 */
export async function updateSystemSettings(settings: SystemSettings): Promise<SystemSettings> {
  const { data } = await api.put<SystemSettings>('/api/settings/', settings);
  return data;
}
