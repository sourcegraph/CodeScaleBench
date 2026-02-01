```java
package com.wellsphere.connect.viewmodel;

import static org.junit.Assert.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import androidx.arch.core.executor.testing.InstantTaskExecutorRule;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;

import com.wellsphere.connect.model.FeedItem;
import com.wellsphere.connect.repository.FeedRepository;
import com.wellsphere.connect.sync.SyncScheduler;
import com.wellsphere.connect.util.NetworkMonitor;
import com.wellsphere.connect.util.Resource;

import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Unit tests for {@link FeedViewModel}.
 *
 * The ViewModel plays a pivotal role in the MVVM stack, so these tests verify that:
 *  • Loading / success / error states are propagated as expected
 *  • Network-dependent refresh paths behave correctly in both online and offline modes
 *  • Side-effects (e.g., background sync) are dispatched only when appropriate
 *
 * NOTE: Production classes such as FeedItem, Resource, FeedRepository, etc. are part of the
 * WellSphere Connect code-base.  Where their implementations are non-trivial, Mockito stubs are
 * used to isolate the ViewModel’s behaviour.
 */
public class FeedViewModelTest {

    @Rule
    public final InstantTaskExecutorRule instantTaskExecutorRule = new InstantTaskExecutorRule();

    @Mock private FeedRepository feedRepository;
    @Mock private SyncScheduler syncScheduler;
    @Mock private NetworkMonitor networkMonitor;

    private FeedViewModel viewModel;

    // LiveData that drives the ViewModel; configured in each test case
    private MutableLiveData<Resource<List<FeedItem>>> feedLiveData;

    @Before
    public void setUp() {
        MockitoAnnotations.openMocks(this);
        feedLiveData = new MutableLiveData<>();
        when(feedRepository.getFeed()).thenReturn(feedLiveData);

        // Default to “online” unless otherwise specified by a test
        when(networkMonitor.isConnected()).thenReturn(true);

        viewModel = new FeedViewModel(feedRepository, syncScheduler, networkMonitor);
    }

    @Test
    public void fetchFeed_success_emitsLoadingThenSuccess() throws InterruptedException {
        // Arrange
        List<FeedItem> fakeItems = Arrays.asList(
                new FeedItem("1", "First post"),
                new FeedItem("2", "Second post")
        );

        // Act
        viewModel.fetchFeed();                       // triggers repository.getFeed()
        feedLiveData.postValue(Resource.loading());  // loading state
        feedLiveData.postValue(Resource.success(fakeItems));

        // Assert
        List<Resource<List<FeedItem>>> emissions =
                getOrAwaitValues(viewModel.getFeed(), 2 /** expected emissions */);

        assertEquals(Resource.Status.LOADING, emissions.get(0).status);
        assertEquals(Resource.Status.SUCCESS, emissions.get(1).status);
        assertEquals(fakeItems, emissions.get(1).data);

        // Side-effect: Sync should be queued once feed is successfully obtained
        verify(syncScheduler).scheduleIncrementalSync();
    }

    @Test
    public void fetchFeed_error_emitsLoadingThenError() throws InterruptedException {
        // Arrange
        Throwable boom = new RuntimeException("Backend failure");

        // Act
        viewModel.fetchFeed();
        feedLiveData.postValue(Resource.loading());
        feedLiveData.postValue(Resource.error(boom));

        // Assert
        List<Resource<List<FeedItem>>> emissions =
                getOrAwaitValues(viewModel.getFeed(), 2);

        assertEquals(Resource.Status.LOADING, emissions.get(0).status);
        assertEquals(Resource.Status.ERROR, emissions.get(1).status);
        assertEquals(boom, emissions.get(1).error);

        // No sync if there was an error
        verify(syncScheduler, never()).scheduleIncrementalSync();
    }

    @Test
    public void refreshFeed_offline_usesCacheAndSkipsSync() throws InterruptedException {
        // Arrange
        when(networkMonitor.isConnected()).thenReturn(false);

        List<FeedItem> cachedItems = Arrays.asList(new FeedItem("c-1", "Cached"));
        feedLiveData.postValue(Resource.success(cachedItems));

        // Act
        viewModel.refreshFeed();

        // Assert
        List<Resource<List<FeedItem>>> emissions = getOrAwaitValues(viewModel.getFeed(), 1);
        assertEquals(cachedItems, emissions.get(0).data);

        // Sync should NOT be scheduled when offline
        verify(syncScheduler, never()).scheduleIncrementalSync();
    }

    @Test
    public void refreshFeed_online_triggersRepositoryAndSync() {
        // Arrange
        when(networkMonitor.isConnected()).thenReturn(true);

        // Act
        viewModel.refreshFeed();

        // Assert
        verify(feedRepository).refresh();           // repository asked to reload from network
        verify(syncScheduler).scheduleIncrementalSync();
    }

    // ---------------------------------------------------------------------------------------------
    // Helper utilities
    // ---------------------------------------------------------------------------------------------

    /**
     * Collects the next N values emitted by a LiveData within a reasonable timeout.
     *
     * @param liveData   The source LiveData
     * @param emissionCt Number of emissions to wait for
     * @param <T>        Type carried by LiveData
     */
    private static <T> List<T> getOrAwaitValues(LiveData<T> liveData, int emissionCt)
            throws InterruptedException {

        CountDownLatch latch = new CountDownLatch(emissionCt);
        List<T> values = new java.util.concurrent.CopyOnWriteArrayList<>();

        liveData.observeForever(value -> {
            values.add(value);
            latch.countDown();
        });

        // Fail the test if the values aren't emitted promptly
        if (!latch.await(3, TimeUnit.SECONDS)) {
            fail("LiveData emissions timed out");
        }
        return values;
    }
}
```