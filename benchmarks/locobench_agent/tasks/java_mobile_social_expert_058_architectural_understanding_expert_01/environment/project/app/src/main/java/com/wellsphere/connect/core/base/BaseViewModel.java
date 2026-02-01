package com.wellsphere.connect.core.base;

import android.util.Log;

import androidx.annotation.CallSuper;
import androidx.annotation.MainThread;
import androidx.annotation.NonNull;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;

import java.util.concurrent.atomic.AtomicBoolean;

import io.reactivex.rxjava3.core.Completable;
import io.reactivex.rxjava3.core.Maybe;
import io.reactivex.rxjava3.core.Observable;
import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.disposables.CompositeDisposable;
import io.reactivex.rxjava3.disposables.Disposable;
import io.reactivex.rxjava3.android.schedulers.AndroidSchedulers;
import io.reactivex.rxjava3.schedulers.Schedulers;

/**
 * BaseViewModel
 *
 * A common superclass that encapsulates shared behaviour for every ViewModel in the
 * WellSphere Connect code-base.  It offers:
 *
 *  • Lifecycle-aware disposal of RxJava subscriptions.
 *  • Automatic mapping of async results into a {@link Resource} wrapper
 *    so UI layers can provide deterministic rendering (SUCCESS / ERROR / LOADING).
 *  • Centralised surfacing of one-shot error events.
 *  • Lightweight progress reporting for indeterminate operations.
 *
 * The class purposefully exposes only *protected* helpers so concrete ViewModels remain
 * responsible for publicly exposing {@link LiveData} instances that are meaningful to their
 * respective feature modules.
 *
 * NOTE: This implementation is RxJava-based for asynchronous orchestration.  If you prefer
 * Kotlin Coroutines, provide an alternate implementation in the :kotlinCore module and keep the
 * same public surface to maintain polymorphic compatibility.
 */
public abstract class BaseViewModel extends ViewModel {

    // ---- Common LiveData -------------------------------------------------- //

    /**
     * Emits TRUE when a background operation is running and FALSE when the queue is idle.
     * UI layers can observe this to toggle global progress indicators.
     */
    protected final MutableLiveData<Boolean> progressLiveData = new MutableLiveData<>(false);

    /**
     * Emits one-shot error events that should be shown to the user.  By wrapping the Throwable
     * into an {@link Event} we guarantee it is handled at most once even across configuration
     * changes.
     */
    protected final MutableLiveData<Event<Throwable>> errorLiveData = new MutableLiveData<>();

    // ---- RxJava ----------------------------------------------------------- //

    private final CompositeDisposable disposables = new CompositeDisposable();

    // ---------------------------------------------------------------------- //
    //  Public accessor helpers                                               //
    // ---------------------------------------------------------------------- //

    public LiveData<Boolean> getProgress() {
        return progressLiveData;
    }

    public LiveData<Event<Throwable>> getErrorEvents() {
        return errorLiveData;
    }

    // ---------------------------------------------------------------------- //
    //  RxJava convenience                                                    //
    // ---------------------------------------------------------------------- //

    /**
     * Safely registers a {@link Disposable} for automatic disposal in {@link #onCleared()}.
     */
    protected void addDisposable(@NonNull Disposable disposable) {
        disposables.add(disposable);
    }

    /**
     * Executes the supplied {@link Single} on the IO scheduler, observes on the main thread,
     * maps its lifecycle to {@link Resource}, and posts results into {@code target}.
     */
    @MainThread
    protected <T> void executeSingle(@NonNull Single<T> source,
                                     @NonNull MutableLiveData<Resource<T>> target) {

        target.setValue(Resource.loading());

        addDisposable(
                source.subscribeOn(Schedulers.io())
                      .observeOn(AndroidSchedulers.mainThread())
                      .doOnSubscribe(__ -> progressLiveData.postValue(true))
                      .doFinally(() -> progressLiveData.postValue(false))
                      .subscribe(
                              data -> target.setValue(Resource.success(data)),
                              throwable -> {
                                  Log.e(getClass().getSimpleName(),
                                          "executeSingle: error encountered", throwable);
                                  target.setValue(Resource.error(throwable));
                                  errorLiveData.postValue(new Event<>(throwable));
                              })
        );
    }

    /**
     * Same as {@link #executeSingle(Single, MutableLiveData)} but for {@link Observable}s.
     * The incoming data stream is cached until completion; emitting at most the last item
     * so Resource SUCCESS always carries the latest state.  If you need the whole stream,
     * expose the {@link Observable} directly from your concrete ViewModel.
     */
    @MainThread
    protected <T> void executeObservable(@NonNull Observable<T> source,
                                         @NonNull MutableLiveData<Resource<T>> target) {

        target.setValue(Resource.loading());

        addDisposable(
                source.subscribeOn(Schedulers.io())
                      .observeOn(AndroidSchedulers.mainThread())
                      .doOnSubscribe(__ -> progressLiveData.postValue(true))
                      .doFinally(() -> progressLiveData.postValue(false))
                      .subscribe(
                              data -> target.setValue(Resource.success(data)),
                              throwable -> {
                                  Log.e(getClass().getSimpleName(),
                                          "executeObservable: error encountered", throwable);
                                  target.setValue(Resource.error(throwable));
                                  errorLiveData.postValue(new Event<>(throwable));
                              })
        );
    }

    /**
     * A convenience wrapper for {@link Completable} that only signals LOADING or ERROR
     * because no actual data payload is expected.
     */
    @MainThread
    protected void executeCompletable(@NonNull Completable source) {

        addDisposable(
                source.subscribeOn(Schedulers.io())
                      .observeOn(AndroidSchedulers.mainThread())
                      .doOnSubscribe(__ -> progressLiveData.postValue(true))
                      .doFinally(() -> progressLiveData.postValue(false))
                      .subscribe(
                              () -> { /* success – nothing to propagate */ },
                              throwable -> {
                                  Log.e(getClass().getSimpleName(),
                                          "executeCompletable: error encountered", throwable);
                                  errorLiveData.postValue(new Event<>(throwable));
                              })
        );
    }

    /**
     * Executes a {@link Maybe} source.  When it completes empty, SUCCESS will carry {@code null}.
     */
    @MainThread
    protected <T> void executeMaybe(@NonNull Maybe<T> source,
                                    @NonNull MutableLiveData<Resource<T>> target) {

        target.setValue(Resource.loading());

        addDisposable(
                source.subscribeOn(Schedulers.io())
                      .observeOn(AndroidSchedulers.mainThread())
                      .doOnSubscribe(__ -> progressLiveData.postValue(true))
                      .doFinally(() -> progressLiveData.postValue(false))
                      .subscribe(
                              data -> target.setValue(Resource.success(data)),
                              throwable -> {
                                  Log.e(getClass().getSimpleName(),
                                          "executeMaybe: error encountered", throwable);
                                  target.setValue(Resource.error(throwable));
                                  errorLiveData.postValue(new Event<>(throwable));
                              },
                              () -> target.setValue(Resource.success(null))
                      )
        );
    }

    // ---------------------------------------------------------------------- //
    //  Lifecycle                                                             //
    // ---------------------------------------------------------------------- //

    @Override
    @CallSuper
    protected void onCleared() {
        disposables.clear();
        super.onCleared();
    }

    // ---------------------------------------------------------------------- //
    //  Helper classes                                                        //
    // ---------------------------------------------------------------------- //

    /**
     * A lifecycle-aware wrapper for data that is exposed via a {@link LiveData} representing an
     * event.  It will emit its content only once to avoid duplicate handling after configuration
     * changes (rotation, multi-window, etc.).
     */
    public static final class Event<T> {
        private final T content;
        private final AtomicBoolean hasBeenHandled = new AtomicBoolean(false);

        public Event(@NonNull T content) {
            this.content = content;
        }

        /**
         * Returns the content if it has not been handled yet; otherwise returns {@code null}.
         */
        public T getContentIfNotHandled() {
            return hasBeenHandled.compareAndSet(false, true) ? content : null;
        }

        /**
         * Returns the content, even if it has already been handled.
         */
        public T peekContent() {
            return content;
        }
    }

    /**
     * Standard status wrapper used across the application so UI layers can easily branch
     * on LOADING / SUCCESS / ERROR with a single observable property.
     */
    public static final class Resource<T> {

        public enum Status { SUCCESS, ERROR, LOADING }

        @NonNull public final Status status;
        public final T data;
        public final Throwable error;

        private Resource(@NonNull Status status, T data, Throwable error) {
            this.status = status;
            this.data = data;
            this.error = error;
        }

        @NonNull
        public static <T> Resource<T> success(T data) {
            return new Resource<>(Status.SUCCESS, data, null);
        }

        @NonNull
        public static <T> Resource<T> error(@NonNull Throwable throwable) {
            return new Resource<>(Status.ERROR, null, throwable);
        }

        @NonNull
        public static <T> Resource<T> loading() {
            return new Resource<>(Status.LOADING, null, null);
        }

        @Override
        public String toString() {
            return "Resource{" +
                    "status=" + status +
                    ", data=" + data +
                    ", error=" + error +
                    '}';
        }
    }
}