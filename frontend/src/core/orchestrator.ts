/**
 * Orchestrator — parallel TaskAgent architecture with tier-based dependency execution.
 * Port of backend/orchestrator/orchestrator.py for frontend use.
 *
 * Pipeline:
 *   Phase 1: MainAgent decompose (single LLM call)
 *   Phase 2: TaskAgent tier-based execution (parallel within tier, sequential across tiers)
 *   Phase 3: MainAgent summarize (single LLM call, multi-task only)
 */

import { MainAgent } from './agents/main-agent'
import { TaskAgent } from './agents/task-agent'
import { commandValidator } from './skills/command-validator'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_PARALLEL_TASKS = 4
const SESSION_STATE_TTL = 600_000 // 10 minutes in ms

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SSEEvent {
  event: string
  data: Record<string, any>
}

// ---------------------------------------------------------------------------
// TaskManager — manages parallel execution of tasks within a single request
// ---------------------------------------------------------------------------

class TaskManager {
  decomposition: Record<string, any>
  tasks: Array<Record<string, any>>
  taskStates: Map<string, Record<string, any>> = new Map()
  private completedResults: Map<string, Record<string, any>> = new Map()
  private userAnswers: Map<string, string> = new Map()
  createdAt: number

  constructor(decomposition: Record<string, any>) {
    this.decomposition = decomposition
    this.tasks = decomposition.tasks ?? []
    this.createdAt = Date.now()
  }

  isExpired(): boolean {
    return Date.now() - this.createdAt > SESSION_STATE_TTL
  }

  allCompleted(): boolean {
    for (const taskDef of this.tasks) {
      const tid = taskDef.task_id ?? ''
      const state = this.taskStates.get(tid)
      const status = state?.status ?? 'pending'
      if (status !== 'completed' && status !== 'failed') {
        return false
      }
    }
    return true
  }

  hasPendingWork(): boolean {
    for (const taskDef of this.tasks) {
      const tid = taskDef.task_id ?? ''
      const state = this.taskStates.get(tid)
      const status = state?.status ?? 'pending'
      if (status === 'pending' || status === 'blocked') {
        return true
      }
    }
    return false
  }

  getCompletedResults(): Array<Record<string, any>> {
    const results: Array<Record<string, any>> = []
    for (const taskDef of this.tasks) {
      const tid = taskDef.task_id ?? ''
      const state = this.taskStates.get(tid)
      if (state?.status === 'completed') {
        results.push({
          task_id: tid,
          description: taskDef.description ?? '',
          execution_mode: taskDef.execution_mode ?? 'continuous',
          result: state.result ?? {},
        })
      }
    }
    return results
  }

  // ----- Tier computation (topological sort) -----

  private computeTiers(): Array<Array<Record<string, any>>> {
    const taskMap = new Map<string, Record<string, any>>()
    for (const td of this.tasks) {
      taskMap.set(td.task_id ?? '', td)
    }

    const assigned = new Map<string, number>()
    const tiers: Array<Array<Record<string, any>>> = []
    const remaining = new Set(taskMap.keys())

    while (remaining.size > 0) {
      const currentTier: Array<Record<string, any>> = []

      for (const tid of remaining) {
        const deps: string[] = taskMap.get(tid)!.depends_on ?? []
        if (deps.every((d) => assigned.has(d))) {
          currentTier.push(taskMap.get(tid)!)
          assigned.set(tid, tiers.length)
        }
      }

      if (currentTier.length === 0) {
        // Cycle detected — force remaining into this tier
        console.warn(
          '[TaskManager] Cycle detected in task dependencies, forcing remaining:',
          [...remaining],
        )
        for (const tid of remaining) {
          currentTier.push(taskMap.get(tid)!)
          assigned.set(tid, tiers.length)
        }
      }

      for (const td of currentTier) {
        remaining.delete(td.task_id ?? '')
      }

      tiers.push(currentTier)
    }

    return tiers
  }

  // ----- Tier-based execution -----

  async *executeAll(): AsyncGenerator<SSEEvent> {
    const tiers = this.computeTiers()

    for (let tierIdx = 0; tierIdx < tiers.length; tierIdx++) {
      const tierTasks = tiers[tierIdx]
      if (!tierTasks || tierTasks.length === 0) continue

      console.info(
        `[TaskManager] Executing tier ${tierIdx} with ${tierTasks.length} task(s):`,
        tierTasks.map((t) => t.task_id),
      )

      // Inject predecessor context for dependent tasks
      for (const td of tierTasks) {
        this.injectPredecessorContext(td)
      }

      // Execute tier tasks in parallel
      for await (const event of this.executeTier(tierTasks)) {
        yield event
      }

      // Check if any tasks in this tier paused or failed
      const tierIds = new Set(tierTasks.map((td) => td.task_id ?? ''))
      let hasBlocker = false
      for (const tid of tierIds) {
        const status = this.taskStates.get(tid)?.status ?? 'pending'
        if (status === 'paused' || status === 'failed') {
          hasBlocker = true
          break
        }
      }

      if (hasBlocker) {
        // Mark downstream tasks as blocked
        this.markDownstreamBlocked(tierIds, tiers, tierIdx)
        break
      }
    }
  }

  private async *executeTier(
    tierTasks: Array<Record<string, any>>,
  ): AsyncGenerator<SSEEvent> {
    const events: SSEEvent[] = []
    const semaphore = MAX_PARALLEL_TASKS

    const runTask = async (taskDef: Record<string, any>): Promise<void> => {
      const tid = taskDef.task_id ?? ''
      const agent = new TaskAgent()
      try {
        for await (const event of agent.execute(taskDef)) {
          if (event.event === 'task_update') {
            const data = event.data ?? {}
            this.taskStates.set(tid, data)
            if (data.status === 'completed') {
              this.completedResults.set(tid, data.result ?? {})
            }
          }
          events.push(event as SSEEvent)
        }
      } catch (e: any) {
        console.error(`[TaskAgent ${tid}] crashed:`, e)
        const errorData = { task_id: tid, status: 'failed', error: String(e) }
        this.taskStates.set(tid, errorData)
        events.push({ event: 'task_update', data: errorData })
      }
    }

    // Execute tasks in batches limited by semaphore
    const batches: Array<Array<Record<string, any>>> = []
    for (let i = 0; i < tierTasks.length; i += semaphore) {
      batches.push(tierTasks.slice(i, i + semaphore))
    }

    for (const batch of batches) {
      events.length = 0
      await Promise.all(batch.map((td) => runTask(td)))
      for (const event of events) {
        yield event
      }
    }
  }

  // ----- Dependency helpers -----

  private injectPredecessorContext(taskDef: Record<string, any>): void {
    const deps: string[] = taskDef.depends_on ?? []
    if (deps.length === 0) return

    const contextParts: string[] = []
    for (const depId of deps) {
      const depResult = this.completedResults.get(depId)
      if (!depResult) continue

      const resultType = depResult.type ?? ''
      // Find the description of the predecessor task
      let depDesc = ''
      for (const td of this.tasks) {
        if (td.task_id === depId) {
          depDesc = td.description ?? ''
          break
        }
      }

      // Inject user answer from resumed predecessor (if any)
      const userAnswer = this.userAnswers.get(depId)
      if (userAnswer) {
        contextParts.push(
          `用户在前置任务 ${depId}（${depDesc}）中的回答：${userAnswer}`,
        )
      }

      if (resultType === 'single_command') {
        const cmdObj = depResult.command ?? {}
        const cmdStr = typeof cmdObj === 'object' ? (cmdObj.command ?? '') : ''
        const explanation = typeof cmdObj === 'object' ? (cmdObj.explanation ?? '') : ''
        contextParts.push(
          `前置任务 ${depId}（${depDesc}）已生成命令：${cmdStr}`,
        )
        if (explanation) {
          contextParts.push(`说明：${explanation}`)
        }
      } else if (resultType === 'project') {
        const cmds: string[] = []
        for (const phase of depResult.phases ?? []) {
          for (const task of phase.tasks ?? []) {
            for (const block of task.command_blocks ?? []) {
              const c = block.command ?? ''
              if (c) cmds.push(c)
            }
          }
        }
        contextParts.push(
          `前置任务 ${depId}（${depDesc}）已生成命令：${cmds.join('; ')}`,
        )
      }
    }

    if (contextParts.length > 0) {
      const predecessorText = contextParts.join('\n')
      taskDef.user_request = `${taskDef.user_request}\n\n## 前置任务结果\n${predecessorText}`
    }
  }

  private markDownstreamBlocked(
    blockerIds: Set<string>,
    tiers: Array<Array<Record<string, any>>>,
    currentTierIdx: number,
  ): void {
    // Collect all task IDs that are paused/failed (direct blockers)
    const failedOrPaused = new Set<string>()
    for (const tid of blockerIds) {
      const status = this.taskStates.get(tid)?.status ?? ''
      if (status === 'paused' || status === 'failed') {
        failedOrPaused.add(tid)
      }
    }

    if (failedOrPaused.size === 0) return

    // Walk remaining tiers and mark tasks whose deps intersect with blockers
    const blockedIds = new Set(failedOrPaused)
    for (let i = currentTierIdx + 1; i < tiers.length; i++) {
      for (const td of tiers[i]) {
        const tid = td.task_id ?? ''
        const deps = new Set<string>(td.depends_on ?? [])
        // Check intersection
        let hasIntersection = false
        for (const d of deps) {
          if (blockedIds.has(d)) {
            hasIntersection = true
            break
          }
        }
        if (hasIntersection) {
          blockedIds.add(tid)
          this.taskStates.set(tid, { task_id: tid, status: 'blocked' })
        }
      }
    }
  }

  // ----- Resume + unblock -----

  async *resumeTask(
    taskId: string,
    userAnswer: string,
  ): AsyncGenerator<SSEEvent> {
    // Find the task definition
    let taskDef: Record<string, any> | null = null
    for (const td of this.tasks) {
      if (td.task_id === taskId) {
        taskDef = { ...td }
        break
      }
    }

    if (!taskDef) {
      yield {
        event: 'error',
        data: { message: `Task ${taskId} not found` },
      }
      return
    }

    // Store user answer for downstream context injection
    this.userAnswers.set(taskId, userAnswer)

    // Append user answer to the request
    taskDef.user_request = `${taskDef.user_request}\n\n用户补充信息：${userAnswer}`

    const agent = new TaskAgent()
    for await (const event of agent.execute(taskDef)) {
      if (event.event === 'task_update') {
        const data = event.data ?? {}
        this.taskStates.set(taskId, data)
        if (data.status === 'completed') {
          this.completedResults.set(taskId, data.result ?? {})
        }
      }
      yield event as SSEEvent
    }

    // After resuming, try to execute newly unblocked downstream tasks
    for await (const event of this.executeUnblocked()) {
      yield event
    }
  }

  private async *executeUnblocked(): AsyncGenerator<SSEEvent> {
    while (true) {
      const newlyReady: Array<Record<string, any>> = []
      for (const td of this.tasks) {
        const tid = td.task_id ?? ''
        const state = this.taskStates.get(tid)
        const status = state?.status ?? 'pending'

        if (status !== 'blocked' && status !== 'pending') continue

        const deps: string[] = td.depends_on ?? []
        if (deps.length === 0) {
          if (status === 'pending') {
            newlyReady.push(td)
          }
          continue
        }

        const allDepsDone = deps.every(
          (d) => this.taskStates.get(d)?.status === 'completed',
        )
        if (allDepsDone) {
          newlyReady.push(td)
        }
      }

      if (newlyReady.length === 0) break

      console.info(
        `[TaskManager] Unblocked ${newlyReady.length} task(s):`,
        newlyReady.map((t) => t.task_id),
      )

      // Inject predecessor context and execute
      for (const td of newlyReady) {
        this.injectPredecessorContext(td)
      }

      for await (const event of this.executeTier(newlyReady)) {
        yield event
      }

      // Check if any paused/failed — stop further unblocking
      let hasBlocker = false
      for (const td of newlyReady) {
        const tid = td.task_id ?? ''
        const status = this.taskStates.get(tid)?.status ?? ''
        if (status === 'paused' || status === 'failed') {
          hasBlocker = true
          break
        }
      }

      if (hasBlocker) break
    }
  }
}

// ---------------------------------------------------------------------------
// Orchestrator — main entry point
// ---------------------------------------------------------------------------

/**
 * SSE event contract:
 *   event: thinking      -> {text}
 *   event: task_list     -> {project_name, overview, tasks: [{task_id, description, status}]}
 *   event: task_update   -> {task_id, status, result?, questions?, error?}
 *   event: task_thinking -> {task_id, text}
 *   event: summary       -> {type, commands[], explanation, command_blocks[], project?}
 *   event: content       -> {type: "single_command|conversation|project", ...}
 *   event: done          -> {timestamp?}
 *   event: error         -> {message}
 */
export class Orchestrator {
  private mainAgent = new MainAgent()
  private activeSessions = new Map<string, TaskManager>()

  /**
   * Process a user message and yield SSE events.
   */
  async *processMessage(
    userInput: string,
    sessionContext: string = '',
    sessionId: string = '',
    taskId?: string,
  ): AsyncGenerator<SSEEvent> {
    // Clean up expired sessions
    this.cleanupExpired()

    // --- Case A: Resuming a paused task ---
    if (taskId && this.activeSessions.has(sessionId)) {
      for await (const event of this.resumeTask(sessionId, taskId, userInput)) {
        yield event
      }
      return
    }

    // --- Case B: New message with active session -> cancel old, start fresh ---
    if (this.activeSessions.has(sessionId)) {
      this.activeSessions.delete(sessionId)
    }

    // --- Case C: New request -> pipeline ---

    // Phase 1: MainAgent decompose
    yield { event: 'thinking', data: { text: '正在分析您的需求...\n' } }

    const decomposition = await this.mainAgent.decompose(userInput, sessionContext)

    const thinking = decomposition._thinking ?? ''
    delete decomposition._thinking
    if (thinking) {
      yield { event: 'thinking', data: { text: thinking } }
    }

    const tasks: Array<Record<string, any>> = decomposition.tasks ?? []
    const isSingle = decomposition.is_single_task ?? tasks.length <= 1

    if (tasks.length === 0) {
      yield {
        event: 'content',
        data: {
          type: 'conversation',
          message: '抱歉，我无法理解您的需求。请尝试更详细地描述。',
          questions: [],
        },
      }
      yield { event: 'done', data: {} }
      return
    }

    // Emit task list
    const hasDeps = tasks.some((t) => (t.depends_on ?? []).length > 0)
    yield {
      event: 'task_list',
      data: {
        project_name: decomposition.project_name ?? '',
        overview: decomposition.overview ?? '',
        tasks: tasks.map((t, i) => ({
          task_id: t.task_id ?? String(i + 1),
          description: t.description ?? `任务 ${i + 1}`,
          depends_on: t.depends_on ?? [],
          status: (t.depends_on ?? []).length > 0 ? 'blocked' : 'pending',
        })),
      },
    }

    // Phase 2: TaskAgent tier-based execution
    if (hasDeps) {
      yield {
        event: 'thinking',
        data: { text: `正在按依赖顺序执行 ${tasks.length} 个任务...\n` },
      }
    } else {
      yield {
        event: 'thinking',
        data: { text: `正在并行执行 ${tasks.length} 个任务...\n` },
      }
    }

    const mgr = new TaskManager(decomposition)
    if (sessionId) {
      this.activeSessions.set(sessionId, mgr)
    }

    for await (const event of mgr.executeAll()) {
      yield event
    }

    // Check if any tasks are paused
    if (!mgr.allCompleted()) {
      yield { event: 'done', data: {} }
      return
    }

    // Phase 3: Summarize (only for multi-task)
    const completedResults = mgr.getCompletedResults()

    if (isSingle && completedResults.length === 1) {
      // Single task — emit result directly
      let result = completedResults[0].result ?? {}
      const resultType = result.type ?? ''

      if (resultType === 'project') {
        result = await this.postProcessProject(result)
      }

      yield { event: 'content', data: result }
    } else {
      // Multi-task — LLM summarize
      yield { event: 'thinking', data: { text: '正在汇总所有任务结果...\n' } }

      const summary = await this.mainAgent.summarize(userInput, completedResults)
      const summaryThinking = summary._thinking ?? ''
      delete summary._thinking
      if (summaryThinking) {
        yield { event: 'thinking', data: { text: summaryThinking } }
      }

      // Build project data from summary
      let projectData = this.buildProjectFromSummary(
        decomposition,
        summary,
        completedResults,
      )

      // Post-process (validation)
      projectData = await this.postProcessProject(projectData)

      yield { event: 'content', data: projectData }
    }

    // Clean up session state
    if (sessionId && this.activeSessions.has(sessionId)) {
      this.activeSessions.delete(sessionId)
    }

    yield { event: 'done', data: { timestamp: Date.now() } }
  }

  // ----- Resume paused task -----

  private async *resumeTask(
    sessionId: string,
    taskId: string,
    userAnswer: string,
  ): AsyncGenerator<SSEEvent> {
    const mgr = this.activeSessions.get(sessionId)
    if (!mgr) {
      yield { event: 'error', data: { message: 'Session not found' } }
      return
    }

    console.info(
      `[Orchestrator] Resuming task ${taskId} in session ${sessionId} with answer: ${userAnswer.slice(0, 80)}`,
    )

    for await (const event of mgr.resumeTask(taskId, userAnswer)) {
      yield event
    }

    // Check if all tasks now completed
    if (mgr.allCompleted()) {
      const decomposition = mgr.decomposition
      const isSingle = decomposition.is_single_task ?? false
      const completedResults = mgr.getCompletedResults()

      if (isSingle && completedResults.length === 1) {
        let result = completedResults[0].result ?? {}
        const resultType = result.type ?? ''

        if (resultType === 'project') {
          result = await this.postProcessProject(result)
        }

        yield { event: 'content', data: result }
      } else {
        yield { event: 'thinking', data: { text: '正在汇总所有任务结果...\n' } }

        const origInput = decomposition._original_input ?? userAnswer
        const summary = await this.mainAgent.summarize(origInput, completedResults)
        delete summary._thinking

        let projectData = this.buildProjectFromSummary(
          decomposition,
          summary,
          completedResults,
        )
        projectData = await this.postProcessProject(projectData)

        yield { event: 'content', data: projectData }
      }

      // Clean up
      if (this.activeSessions.has(sessionId)) {
        this.activeSessions.delete(sessionId)
      }
    }

    yield { event: 'done', data: { timestamp: Date.now() } }
  }

  // ----- Post-processing -----

  private async postProcessProject(projectData: Record<string, any>): Promise<Record<string, any>> {
    const thinkingValue = projectData.thinking

    const projectObj = projectData.project ?? projectData

    // Collect all commands for validation
    const allCommands: string[] = []
    for (const phase of projectObj.phases ?? []) {
      for (const task of phase.tasks ?? []) {
        for (const block of task.command_blocks ?? []) {
          const cmd = block.command ?? ''
          if (cmd) allCommands.push(cmd)
        }
      }
    }

    if (allCommands.length > 0) {
      try {
        const results = await commandValidator.validate(allCommands)
        const errorCount = results.filter((r: any) => !r.valid).length
        projectObj.validation_summary = {
          total_commands: allCommands.length,
          errors: errorCount,
          valid: errorCount === 0,
        }
      } catch (e: any) {
        console.warn('[Orchestrator] Project validation failed:', e)
      }
    }

    const result: Record<string, any> = { type: 'project', ...projectObj }
    if (thinkingValue) {
      result.thinking = thinkingValue
    }
    return result
  }

  private buildProjectFromSummary(
    decomposition: Record<string, any>,
    summary: Record<string, any>,
    completedResults: Array<Record<string, any>>,
  ): Record<string, any> {
    const phases = summary.phases ?? []

    // If summary provided valid phases with command_blocks, use them
    if (
      phases.length > 0 &&
      phases.some((p: any) =>
        (p.tasks ?? []).some((t: any) => (t.command_blocks ?? []).length > 0),
      )
    ) {
      return {
        type: 'project',
        project_name: decomposition.project_name ?? '',
        overview: summary.explanation ?? decomposition.overview ?? '',
        phases,
      }
    }

    // Fallback: build phases from completed results
    const fallbackPhases: Array<Record<string, any>> = []
    for (const cr of completedResults) {
      const result = cr.result ?? {}
      const resultType = result.type ?? ''
      const tid = cr.task_id ?? ''
      const desc = cr.description ?? ''
      const mode = cr.execution_mode ?? 'continuous'

      if (resultType === 'single_command') {
        const cmdObj = result.command ?? {}
        const cmdStr = typeof cmdObj === 'object' ? (cmdObj.command ?? '') : ''
        const cmdLines = cmdStr
          .split('\n')
          .map((l: string) => l.trim())
          .filter((l: string) => l.length > 0)
        const blocks = this.commandLinesToBlocks(cmdLines, mode)

        const explanation = typeof cmdObj === 'object' ? (cmdObj.explanation ?? '') : ''

        fallbackPhases.push({
          phase_name: desc,
          description: explanation || desc,
          tasks: [
            {
              task_id: tid,
              description: desc,
              commands: cmdLines
                .filter((l: string) => l.length > 0)
                .map((l: string) => l.split(/\s+/)[0].replace(/^\//, '')),
              command_blocks: blocks,
              dependencies: [],
            },
          ],
        })
      } else if (resultType === 'project') {
        const innerPhases = result.phases ?? []
        fallbackPhases.push(...innerPhases)
      }
    }

    return {
      type: 'project',
      project_name: decomposition.project_name ?? '',
      overview: summary.explanation ?? decomposition.overview ?? '',
      phases: fallbackPhases,
    }
  }

  private commandLinesToBlocks(
    cmdLines: string[],
    executionMode: string,
  ): Array<Record<string, any>> {
    if (cmdLines.length === 0) return []

    const blocks: Array<Record<string, any>> = []
    for (let i = 0; i < cmdLines.length; i++) {
      let blockType: string
      let needsRedstone: boolean

      if (i === 0) {
        if (executionMode === 'continuous') {
          blockType = 'repeating'
          needsRedstone = false
        } else {
          blockType = 'impulse'
          needsRedstone = true
        }
      } else {
        blockType = 'chain'
        needsRedstone = false
      }

      blocks.push({
        type: blockType,
        conditional: false,
        needs_redstone: needsRedstone,
        command: cmdLines[i],
        comment: '',
      })
    }

    return blocks
  }

  private cleanupExpired(): void {
    const expired: string[] = []
    for (const [sid, mgr] of this.activeSessions) {
      if (mgr.isExpired()) {
        expired.push(sid)
      }
    }
    for (const sid of expired) {
      this.activeSessions.delete(sid)
      console.info(`[Orchestrator] Cleaned up expired session state: ${sid}`)
    }
  }
}

// Singleton
export const orchestrator = new Orchestrator()
