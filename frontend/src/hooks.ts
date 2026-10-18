import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  reload: () => Promise<void>;
}

/** Load data from the API, exposing loading/error state and a reload function. */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const id = ++latest.current;
    setLoading(true);
    try {
      const result = await loader();
      if (id === latest.current) {
        setData(result);
        setError(undefined);
      }
    } catch (e) {
      if (id === latest.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (id === latest.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, error, loading, reload };
}

/** Run a state-changing action once at a time; exposes pending + error state. */
export function useAction<A extends unknown[], R>(action: (...args: A) => Promise<R>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const inFlight = useRef(false);
  const run = useCallback(async (...args: A): Promise<R | undefined> => {
    if (inFlight.current) return undefined; // ignore double clicks
    inFlight.current = true;
    setPending(true);
    setError(undefined);
    try {
      return await action(...args);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }, [action]);
  return { run, pending, error, clearError: () => setError(undefined) };
}
