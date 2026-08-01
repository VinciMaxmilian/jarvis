/**
 * Metas: listar, criar, expandir e executar.
 *
 * Esta tela não estava na lista de telas do plano, mas o `GoalCard` estava na de
 * componentes e `api/goals.ts` existe — um card sem lugar onde morar é código
 * que ninguém executa. Ela é o lugar.
 *
 * ## Sobre executar de dentro do celular
 *
 * `POST /{goal_id}/execute` roda a decomposição e as tarefas **dentro da
 * requisição** (`goals.py`), o que pode levar minutos. O `executeGoal` já leva
 * timeout próprio de 10 min. O que a tela acrescenta é honestidade: o card fica
 * com spinner, o resto continua utilizável, e ao terminar a lista é recarregada
 * inteira — o servidor mudou mais coisas do que a meta que voltou na resposta.
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
import { createGoal, executeGoal, listGoals, listTasks, type Goal, type Task } from '../api/goals';
import { GoalCard } from '../components/GoalCard';
import { alpha, colors, fonts, radius, spacing } from '../theme/colors';

export default function GoalsScreen() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasksByGoal, setTasksByGoal] = useState<Record<string, Task[]>>({});
  const [loadingTasks, setLoadingTasks] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [executing, setExecuting] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [title, setTitle] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setGoals(await listGoals());
      setError(null);
    } catch (err) {
      setError(describeError(err));
    }
  }, []);

  useEffect(() => {
    void load().finally(() => setLoading(false));
  }, [load]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    // Tarefas em cache viram mentira depois de um refresh: descartar é mais
    // barato (e mais correto) que revalidar meta a meta.
    setTasksByGoal({});
    void load().finally(() => setRefreshing(false));
  }, [load]);

  const toggle = useCallback(
    (goal: Goal) => {
      if (expanded === goal.id) {
        setExpanded(null);
        return;
      }
      setExpanded(goal.id);
      if (tasksByGoal[goal.id]) return;

      setLoadingTasks(goal.id);
      listTasks(goal.id)
        .then((tasks) => setTasksByGoal((current) => ({ ...current, [goal.id]: tasks })))
        .catch((err: unknown) => setError(describeError(err)))
        .finally(() => setLoadingTasks(null));
    },
    [expanded, tasksByGoal],
  );

  const submit = useCallback(async () => {
    const text = title.trim();
    if (!text || creating) return;
    setCreating(true);
    try {
      await createGoal({ title: text });
      setTitle('');
      await load();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setCreating(false);
    }
  }, [title, creating, load]);

  const run = useCallback(
    (goal: Goal) => {
      Alert.alert('Executar meta', `"${goal.title}" será decomposta e executada. Pode demorar.`, [
        { text: 'Cancelar', style: 'cancel' },
        {
          text: 'Executar',
          style: 'default',
          onPress: () => {
            setExecuting(goal.id);
            executeGoal(goal.id)
              .then(() => {
                setTasksByGoal((current) => {
                  const next = { ...current };
                  delete next[goal.id];
                  return next;
                });
                return load();
              })
              .catch((err: unknown) => setError(describeError(err)))
              .finally(() => setExecuting(null));
          },
        },
      ]);
    },
    [load],
  );

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.brand}>METAS</Text>
        <Text style={styles.count}>{goals.length}</Text>
      </View>

      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          value={title}
          onChangeText={setTitle}
          placeholder="Nova meta..."
          placeholderTextColor={colors.textMuted}
          selectionColor={colors.cyan}
          keyboardAppearance="dark"
          returnKeyType="done"
          onSubmitEditing={() => void submit()}
          editable={!creating}
        />
        <Pressable
          onPress={() => void submit()}
          disabled={creating || title.trim().length === 0}
          style={({ pressed }) => [
            styles.add,
            (creating || title.trim().length === 0) && styles.addDisabled,
            pressed && styles.addPressed,
          ]}
          accessibilityRole="button"
          accessibilityLabel="Criar meta"
        >
          {creating ? (
            <ActivityIndicator size="small" color={colors.cyan} />
          ) : (
            <Text style={styles.addText}>+</Text>
          )}
        </Pressable>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.cyan} />
        </View>
      ) : (
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

          {goals.length === 0 ? (
            <Text style={styles.empty}>Nenhuma meta. Crie a primeira acima.</Text>
          ) : (
            goals.map((goal) => (
              <GoalCard
                key={goal.id}
                goal={goal}
                expanded={expanded === goal.id}
                onToggle={() => toggle(goal)}
                tasks={tasksByGoal[goal.id]}
                loadingTasks={loadingTasks === goal.id}
                onExecute={() => run(goal)}
                executing={executing === goal.id}
              />
            ))
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
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
  count: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 10,
  },

  composer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  input: {
    flex: 1,
    height: 42,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
    color: colors.textPrimary,
    fontSize: 14,
  },
  add: {
    width: 46,
    height: 42,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: alpha.cyan(0.35),
    backgroundColor: alpha.cyan(0.14),
  },
  addPressed: { opacity: 0.7 },
  addDisabled: {
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
  },
  addText: {
    color: colors.cyan,
    fontSize: 20,
    lineHeight: 22,
  },

  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  content: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  error: {
    marginBottom: spacing.md,
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 11,
  },
  empty: {
    marginTop: spacing.xxl,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 11,
    textAlign: 'center',
  },
});
