```typescript
/* PaletteFlow Studio — useViewModel Hook
 *
 * The renderer layer (“view”) should never talk to the domain layer directly.
 * Instead, it consumes a View-Model object whose public API is *purely reactive*:
 *
 *     interface MyPanelVm {
 *       readonly state: Readonly<MyPanelState>;
 *       onChange(cb: () => void): () => void;  // subscribe/unsubscribe
 *       dispose(): void;                       // free resources
 *     }
 *
 * A View-Model is typically produced by an application-service or an IoC
 * container that wires domain use-cases to presentation logic.  Because VM
 * instances often maintain observables, async tasks, and plugin hooks, every
 * React component that owns a VM should create it exactly once, re-render
 * whenever it mutates, and tear it down on unmount.  This hook guarantees those
 * invariants while staying concurrent-mode-safe (React 18+).
 */

import {
  DependencyList,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
} from 'react';

import { captureException } from '@/shared/crashReporter'; // renderer side Sentry wrapper
import { log } from '@/shared/logger';                    // tiny winston wrapper

/********************************************************************************
 * Public Types
 ******************************************************************************/

/**
 * The minimal contract a View-Model must fulfil to be consumable by this hook.
 * The hook purposefully stays *very* small so that any state-management library
 * (MobX, RxJS, XState, custom observables…) can be used underneath.
 */
export interface Disposable {
  /**
   * Release every resource that is *not* automatically GC’d:
   *   – subscriptions to global event buses
   *   – web-workers
   *   – file handles
   * DO NOT throw; merely *log*.
   */
  dispose(): void;
}

export interface Subscribable {
  /**
   * Register a listener called *after* the internal state changes.
   * Must return an unsubscribe function.
   */
  onChange(listener: () => void): () => void;
}

/**
 * Generic View-Model contract accepted by the hook.
 */
export type ViewModelLike<S = unknown> = Subscribable &
  Disposable & {
    /** Return a serialisable snapshot the UI can render without further tweaks. */
    getState(): S;
  };

/**
 * Options accepted by the hook.
 */
export interface UseViewModelOptions<S> {
  /**
   * Optional selector that derives a subset of the View-Model state.  Useful for
   * trimming re-render scope or computing expensive projections only when the
   * underlying data actually changed.
   */
  selector?: (state: S) => unknown;
  /**
   * Custom comparison used to decide if `selector(state)` changed.  Defaults to
   * `Object.is`, which handles NaN, -0, +0 correctly.
   */
  equalityFn?: (a: unknown, b: unknown) => boolean;
  /**
   * Whether to dispose the View-Model *immediately* in `useLayoutEffect` (true)
   * or in a passive `useEffect` (false).  The default (false) is often fine,
   * but some tricky cases (e.g. DOM measurement) may need sync disposal.
   */
  syncDispose?: boolean;
}

/*******************************************************************************
 * Hook Implementation
 ******************************************************************************/

/**
 * Typed React hook that spins up any “View-Model-like” object, subscribes the
 * component to its change events through the Concurrent-Mode-safe
 * `useSyncExternalStore`, and disposes the VM on unmount.
 *
 * Usage:
 *
 *   const vm = useViewModel(() => new CanvasPanelVm(deps), [deps]);
 *
 *   // or with state projection:
 *   const { nodes } = useViewModel(
 *     () => new CanvasPanelVm(workspaceId),
 *     [workspaceId],
 *     { selector: (s) => ({ nodes: s.nodes }) }
 *   );
 */
export function useViewModel<S = unknown, VM extends ViewModelLike<S> = ViewModelLike<S>>(
  /**
   * Factory producing a *fresh* View-Model.  It must be referentially-stable
   * across renders, so pass it through `useCallback` if it captures props.
   *
   * IMPORTANT: The factory may throw.  We capture and re-throw after reporting
   * to crash analytics so that the nearest ErrorBoundary handles UI recovery.
   */
  factory: () => VM,
  /**
   * Dependency list that determines when the VM should be recreated.  Follow
   * the exact same rules as `useEffect`’s deps array.
   */
  deps: DependencyList = [],
  /**
   * Additional options.
   */
  options: UseViewModelOptions<S> = {},
): VM {
  const { selector, equalityFn = Object.is, syncDispose = false } = options;

  /**
   * The current View-Model instance.
   * `useRef` is OK here because we handle lifecycle manually.
   */
  const vmRef = useRef<VM>();

  /**
   * Recreate the VM when dependencies change.
   */
  if (vmRef.current === undefined) {
    try {
      vmRef.current = factory();
      if (!vmRef.current) {
        throw new Error('ViewModel factory returned falsy value');
      }
    } catch (err) {
      // Ensure crash analytics capture the context *before* React error boundary
      captureException(err);
      throw err; // Let UI layer handle gracefully
    }
  }

  /**
   * Compose a stable subscribe/getSnapshot pair required by
   * `useSyncExternalStore`.
   */
  const getSnapshot = useMemo(() => {
    const currentVm = vmRef.current!;
    if (selector) {
      let lastSelected = selector(currentVm.getState());
      return () => {
        const nextSelected = selector(currentVm.getState());
        if (!equalityFn(lastSelected, nextSelected)) {
          lastSelected = nextSelected;
        }
        return lastSelected;
      };
    }
    // no selector; just return raw state
    return () => currentVm.getState();
  }, [selector, equalityFn, ...deps]); // must recompute when deps change

  const subscribe = useMemo(() => {
    const currentVm = vmRef.current!;
    return (cb: () => void) => currentVm.onChange(cb);
  }, deps); // recreate when VM replaced

  /**
   * `useSyncExternalStore` handles all
   * – concurrency edge-cases
   * – selective re-render
   * – SSR (not used here but nice to have)
   */
  // eslint-disable-next-line react-hooks/rules-of-hooks
  useSyncExternalStore(subscribe, getSnapshot);

  /**
   * Dispose logic mirror.  We cannot rely on garbage-collection because the VM
   * may hold native handles or global event subscriptions.
   */
  const runDispose = () => {
    const vm = vmRef.current;
    if (vm) {
      try {
        vm.dispose();
      } catch (err) {
        // Disposal should never kill the app; just log
        log.error(err, 'Error during ViewModel.dispose()');
        captureException(err);
      }
      vmRef.current = undefined;
    }
  };

  const useProperEffect = syncDispose ? useLayoutEffect : useEffect;

  // eslint-disable-next-line react-hooks/rules-of-hooks
  useProperEffect(() => {
    // On deps change → VM was created earlier in render phase
    return runDispose; // returned callback executes on unmount or deps change
    // deps matches VM lifecycle:
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return vmRef.current;
}

/*******************************************************************************
 * Convenience Overload
 ******************************************************************************/

/**
 * Overload when caller doesn’t care about selector/equalityFn.
 */
export function useViewModelSimple<S = unknown, VM extends ViewModelLike<S> = ViewModelLike<S>>(
  factory: () => VM,
  deps: DependencyList = [],
): VM {
  return useViewModel(factory, deps);
}
```
