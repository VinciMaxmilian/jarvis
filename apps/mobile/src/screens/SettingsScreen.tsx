/**
 * Configurações do sistema e da sessão.
 *
 * ## Três leituras, três destinos de falha
 *
 * A tela reproduz a separação que o router impõe (`apps/api/routers/settings.py`):
 *
 * - `/providers` — o que dá para escolher. Mapa em memória, não falha.
 * - `/` — o que está persistido. É o que o formulário edita.
 * - `/profiles` — o que está servindo agora. **Pergunta ao provider**, então
 *   demora e falha de verdade quando o LM Studio está desligado.
 *
 * Por isso são três estados de carregamento e não um: `/profiles` fora do ar não
 * pode impedir de trocar de provider — que é justamente o que se faz quando o
 * provider atual está fora do ar.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { describeError } from '../api/client';
import {
  getSystemSettings,
  listProfiles,
  listProviders,
  updateSystemSettings,
  type ProfileCatalog,
  type ProviderOption,
  type SystemSettings,
} from '../api/settings';
import { API_BASE_URL } from '../config';
import { useAuthStore } from '../store/useAuthStore';
import { useChatStore } from '../store/useChatStore';
import { alpha, colors, fonts, radius, spacing } from '../theme/colors';

/** Passo do ajuste de temperatura. Slider exigiria dependência nova. */
const TEMPERATURE_STEP = 0.1;

export default function SettingsScreen() {
  const mode = useAuthStore((state) => state.mode);
  const signOut = useAuthStore((state) => state.signOut);
  const disconnect = useChatStore((state) => state.disconnect);

  const [providers, setProviders] = useState<ProviderOption[]>([]);
  const [profiles, setProfiles] = useState<ProfileCatalog | null>(null);
  const [profilesError, setProfilesError] = useState<string | null>(null);
  const [settings, setSettings] = useState<SystemSettings | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    const [providersResult, settingsResult, profilesResult] = await Promise.allSettled([
      listProviders(),
      getSystemSettings(),
      listProfiles(),
    ]);

    if (providersResult.status === 'fulfilled') setProviders(providersResult.value.providers);

    if (settingsResult.status === 'fulfilled') {
      setSettings(settingsResult.value);
      setError(null);
    } else {
      setError(describeError(settingsResult.reason));
    }

    if (profilesResult.status === 'fulfilled') {
      setProfiles(profilesResult.value);
      setProfilesError(null);
    } else {
      setProfiles(null);
      setProfilesError(describeError(profilesResult.reason));
    }
  }, []);

  useEffect(() => {
    void load().finally(() => setLoading(false));
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void load().finally(() => setRefreshing(false));
  }, [load]);

  const patch = useCallback((changes: Partial<SystemSettings>) => {
    setSaved(false);
    setSettings((current) => (current ? { ...current, ...changes } : current));
  }, []);

  const pickProvider = useCallback(
    (provider: ProviderOption) => {
      // O modelo acompanha o provider. Trocar de provider mantendo o modelo do
      // anterior é o erro mais fácil de cometer aqui, e o router manda o
      // `default_model` de cada um exatamente para evitá-lo.
      patch({ provider: provider.id, model: provider.default_model });
    },
    [patch],
  );

  const save = useCallback(async () => {
    if (!settings || saving) return;
    setSaving(true);
    try {
      // PUT: manda o objeto inteiro. Campo omitido não é preservado, é
      // substituído pelo default do pydantic.
      setSettings(await updateSystemSettings(settings));
      setError(null);
      setSaved(true);
      // As atribuições de perfil dependem do provider salvo — reler é o único
      // jeito de a tela não continuar mostrando a resolução antiga.
      void listProfiles()
        .then((next) => {
          setProfiles(next);
          setProfilesError(null);
        })
        .catch((err: unknown) => {
          setProfiles(null);
          setProfilesError(describeError(err));
        });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSaving(false);
    }
  }, [settings, saving]);

  const confirmSignOut = useCallback(() => {
    Alert.alert('Sair', 'A sessão do Cloudflare Access será apagada deste aparelho.', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Sair',
        style: 'destructive',
        onPress: () => {
          // Derrubar o socket antes: sem isto ele tentaria reconectar com a
          // credencial recém-apagada e tomaria 1008 em laço.
          disconnect();
          void signOut();
        },
      },
    ]);
  }, [disconnect, signOut]);

  if (loading) {
    return (
      <SafeAreaView style={[styles.safe, styles.center]} edges={['top']}>
        <ActivityIndicator color={colors.cyan} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.brand}>AJUSTES</Text>
        {saved && <Text style={styles.savedFlag}>salvo</Text>}
      </View>

      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={colors.cyan}
            colors={[colors.cyan]}
          />
        }
      >
        {error && <Text style={styles.error}>{error}</Text>}

        {settings && (
          <>
            <Text style={styles.sectionTitle}>PROVIDER</Text>
            <View style={styles.chipRow}>
              {providers.map((provider) => {
                const active = provider.id === settings.provider;
                return (
                  <Pressable
                    key={provider.id}
                    onPress={() => pickProvider(provider)}
                    style={[styles.chip, active && styles.chipActive]}
                    accessibilityRole="button"
                  >
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>
                      {provider.id}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.sectionTitle}>MODELO</Text>
            <TextInput
              style={styles.input}
              value={settings.model}
              onChangeText={(model) => patch({ model })}
              placeholder="deixe vazio para o default do provider"
              placeholderTextColor={colors.textMuted}
              selectionColor={colors.cyan}
              keyboardAppearance="dark"
              autoCapitalize="none"
              autoCorrect={false}
            />

            <Text style={styles.sectionTitle}>TEMPERATURA</Text>
            <View style={styles.stepper}>
              <Pressable
                style={styles.stepButton}
                onPress={() =>
                  patch({
                    temperature: Math.max(0, Number((settings.temperature - TEMPERATURE_STEP).toFixed(2))),
                  })
                }
                accessibilityRole="button"
                accessibilityLabel="Diminuir temperatura"
              >
                <Text style={styles.stepText}>−</Text>
              </Pressable>
              <Text style={styles.stepValue}>{settings.temperature.toFixed(2)}</Text>
              <Pressable
                style={styles.stepButton}
                onPress={() =>
                  patch({
                    temperature: Math.min(2, Number((settings.temperature + TEMPERATURE_STEP).toFixed(2))),
                  })
                }
                accessibilityRole="button"
                accessibilityLabel="Aumentar temperatura"
              >
                <Text style={styles.stepText}>+</Text>
              </Pressable>
            </View>

            <Text style={styles.sectionTitle}>SYSTEM PROMPT</Text>
            <TextInput
              style={[styles.input, styles.textarea]}
              value={settings.system_prompt}
              onChangeText={(system_prompt) => patch({ system_prompt })}
              multiline
              selectionColor={colors.cyan}
              keyboardAppearance="dark"
              placeholder="Instruções permanentes do sistema"
              placeholderTextColor={colors.textMuted}
            />

            <Pressable
              onPress={() => void save()}
              disabled={saving}
              style={({ pressed }) => [styles.save, pressed && styles.savePressed]}
              accessibilityRole="button"
            >
              {saving ? (
                <ActivityIndicator size="small" color={colors.cyan} />
              ) : (
                <Text style={styles.saveText}>SALVAR</Text>
              )}
            </Pressable>
          </>
        )}

        <Text style={styles.sectionTitle}>PERFIS EM VIGOR</Text>
        {profilesError ? (
          <Text style={styles.muted}>
            Não deu para perguntar ao provider: {profilesError}
          </Text>
        ) : profiles ? (
          <View style={styles.card}>
            {!profiles.roster_available && (
              <Text style={styles.warn}>
                Roster indisponível — resolução válida, mas não verificada.
              </Text>
            )}
            {profiles.profiles.map((assignment) => (
              <View key={assignment.profile} style={styles.profileRow}>
                <Text style={styles.profileName}>{assignment.profile}</Text>
                <View style={styles.profileRight}>
                  <Text
                    style={[styles.profileModel, assignment.degraded && styles.profileDegraded]}
                    numberOfLines={1}
                  >
                    {assignment.model}
                  </Text>
                  <Text style={styles.profileSource}>{assignment.source}</Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        <Text style={styles.sectionTitle}>SESSÃO</Text>
        <View style={styles.card}>
          <View style={styles.profileRow}>
            <Text style={styles.profileName}>origem</Text>
            <Text style={styles.profileSource} numberOfLines={1}>
              {API_BASE_URL}
            </Text>
          </View>
          <View style={styles.profileRow}>
            <Text style={styles.profileName}>modo</Text>
            <Text style={styles.profileSource}>
              {mode === 'token' ? 'JWT capturado' : mode === 'cookieJar' ? 'cookie do sistema' : '—'}
            </Text>
          </View>
        </View>

        <Pressable
          onPress={confirmSignOut}
          style={({ pressed }) => [styles.signOut, pressed && styles.savePressed]}
          accessibilityRole="button"
        >
          <Text style={styles.signOutText}>SAIR</Text>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  center: { alignItems: 'center', justifyContent: 'center' },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderDim,
  },
  brand: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 12,
    letterSpacing: 2,
  },
  savedFlag: {
    color: colors.green,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  content: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },

  sectionTitle: {
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
    color: colors.textSecondary,
    fontFamily: fonts.mono,
    fontSize: 10,
    letterSpacing: 2,
  },
  error: {
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  muted: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  warn: {
    marginBottom: spacing.sm,
    color: colors.amber,
    fontFamily: fonts.mono,
    fontSize: 10,
  },

  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
  },
  chipActive: {
    borderColor: alpha.cyan(0.45),
    backgroundColor: alpha.cyan(0.16),
  },
  chipText: {
    color: colors.textSecondary,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  chipTextActive: { color: colors.cyan },

  input: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 42,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
    color: colors.textPrimary,
    fontSize: 13,
  },
  textarea: {
    minHeight: 120,
    textAlignVertical: 'top',
  },

  stepper: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  stepButton: {
    width: 44,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
  },
  stepText: {
    color: colors.cyan,
    fontSize: 18,
    lineHeight: 20,
  },
  stepValue: {
    color: colors.textPrimary,
    fontFamily: fonts.mono,
    fontSize: 14,
    minWidth: 52,
    textAlign: 'center',
  },

  save: {
    marginTop: spacing.lg,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: alpha.cyan(0.35),
    backgroundColor: alpha.cyan(0.14),
  },
  savePressed: { opacity: 0.7 },
  saveText: {
    color: colors.cyan,
    fontFamily: fonts.mono,
    fontSize: 12,
    letterSpacing: 2,
  },

  card: {
    padding: spacing.md,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
    gap: spacing.xs,
  },
  profileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  profileName: {
    color: colors.textPrimary,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  profileRight: { flexShrink: 1, alignItems: 'flex-end' },
  profileModel: {
    color: colors.textSecondary,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  profileDegraded: { color: colors.amber },
  profileSource: {
    flexShrink: 1,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 9,
    textAlign: 'right',
  },

  signOut: {
    marginTop: spacing.xl,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: alpha.red(0.35),
    backgroundColor: alpha.red(0.1),
  },
  signOutText: {
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 12,
    letterSpacing: 2,
  },
});
