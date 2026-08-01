/**
 * Card de uma meta, com as tarefas dela quando expandido.
 *
 * As tarefas são carregadas pela tela, não pelo card: `GET /{goal_id}/tasks` é
 * uma requisição por meta, e um card que busca sozinho ao montar dispararia N
 * requisições ao abrir a lista. Aqui o card só pede a expansão; quem decide
 * quando (e se) buscar é quem tem a visão da lista inteira.
 */

import { memo } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { Goal, Task } from '../api/goals';
import { alpha, colors, fonts, radius, spacing, statusColor } from '../theme/colors';

export interface GoalCardProps {
  goal: Goal;
  expanded: boolean;
  onToggle: () => void;
  tasks?: Task[];
  loadingTasks?: boolean;
  onExecute?: () => void;
  executing?: boolean;
}

function StatusBadge({ status }: { status: string }) {
  const tone = statusColor[status] ?? colors.textMuted;
  return (
    <View style={[styles.badge, { borderColor: tone }]}>
      <Text style={[styles.badgeText, { color: tone }]}>{status.toUpperCase()}</Text>
    </View>
  );
}

export const GoalCard = memo(function GoalCard({
  goal,
  expanded,
  onToggle,
  tasks,
  loadingTasks,
  onExecute,
  executing,
}: GoalCardProps) {
  // `draft` e `blocked` são os estados em que executar faz sentido; `active`
  // também (retomada). Terminal não: reexecutar meta concluída é sempre engano.
  const canExecute =
    onExecute !== undefined && ['draft', 'active', 'blocked'].includes(goal.status);

  return (
    <View style={styles.card}>
      <Pressable onPress={onToggle} style={styles.header} accessibilityRole="button">
        <View style={styles.headerText}>
          <Text style={styles.title} numberOfLines={expanded ? undefined : 2}>
            {goal.title}
          </Text>
          <Text style={styles.meta}>
            P{goal.priority} · {new Date(goal.created_at).toLocaleDateString()}
          </Text>
        </View>
        <StatusBadge status={goal.status} />
      </Pressable>

      {expanded && (
        <View style={styles.body}>
          {goal.description ? <Text style={styles.description}>{goal.description}</Text> : null}

          {loadingTasks ? (
            <ActivityIndicator size="small" color={colors.cyan} style={styles.loader} />
          ) : tasks && tasks.length > 0 ? (
            <View style={styles.taskList}>
              {tasks.map((task) => {
                const tone = statusColor[task.status] ?? colors.textMuted;
                return (
                  <View key={task.id} style={styles.task}>
                    <View style={[styles.taskDot, { backgroundColor: tone }]} />
                    <View style={styles.taskText}>
                      <Text style={styles.taskTitle} numberOfLines={2}>
                        {task.title}
                      </Text>
                      <Text style={styles.taskMeta}>
                        {task.status}
                        {task.tool ? ` · ${task.tool}` : ''}
                        {task.attempts > 0 ? ` · ${task.attempts}/${task.max_attempts}` : ''}
                      </Text>
                      {task.error ? (
                        <Text style={styles.taskError} numberOfLines={3}>
                          {task.error}
                        </Text>
                      ) : null}
                    </View>
                  </View>
                );
              })}
            </View>
          ) : (
            <Text style={styles.empty}>Sem tarefas decompostas.</Text>
          )}

          {canExecute && (
            <Pressable
              onPress={onExecute}
              disabled={executing}
              style={({ pressed }) => [
                styles.execute,
                (executing || pressed) && styles.executePressed,
              ]}
              accessibilityRole="button"
            >
              {executing ? (
                <ActivityIndicator size="small" color={colors.green} />
              ) : (
                <Text style={styles.executeText}>EXECUTAR</Text>
              )}
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
});

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderDim,
    backgroundColor: colors.panel,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
    padding: spacing.md,
  },
  headerText: { flex: 1 },
  title: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
    lineHeight: 20,
  },
  meta: {
    marginTop: 2,
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 10,
  },

  badge: {
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  badgeText: {
    fontFamily: fonts.mono,
    fontSize: 9,
    letterSpacing: 0.5,
  },

  body: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.borderDim,
    paddingTop: spacing.md,
  },
  description: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 19,
    marginBottom: spacing.md,
  },
  loader: { alignSelf: 'flex-start' },
  empty: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 11,
  },

  taskList: { gap: spacing.sm },
  task: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  taskDot: {
    width: 7,
    height: 7,
    borderRadius: radius.pill,
    marginTop: 5,
  },
  taskText: { flex: 1 },
  taskTitle: {
    color: colors.textPrimary,
    fontSize: 13,
    lineHeight: 18,
  },
  taskMeta: {
    color: colors.textMuted,
    fontFamily: fonts.mono,
    fontSize: 10,
  },
  taskError: {
    marginTop: 2,
    color: colors.red,
    fontFamily: fonts.mono,
    fontSize: 10,
  },

  execute: {
    marginTop: spacing.md,
    alignSelf: 'flex-start',
    minWidth: 110,
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: alpha.green(0.35),
    backgroundColor: alpha.green(0.12),
  },
  executePressed: {
    backgroundColor: alpha.green(0.24),
  },
  executeText: {
    color: colors.green,
    fontFamily: fonts.mono,
    fontSize: 11,
    letterSpacing: 1,
  },
});
