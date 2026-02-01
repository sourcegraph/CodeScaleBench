```java
package com.wellsphere.connect.ui.feed;

import android.content.res.ColorStateList;
import android.text.format.DateUtils;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.core.content.ContextCompat;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;

import com.bumptech.glide.RequestManager;
import com.wellsphere.connect.R;
import com.wellsphere.connect.domain.model.Post;
import com.wellsphere.connect.util.NetworkUtil;
import com.wellsphere.connect.util.Preconditions;

import java.util.Locale;

/**
 * RecyclerView adapter responsible for rendering a scrolling feed of {@link Post}s.
 *
 * Architectural note:
 *  • This adapter is UI-layer only; it delegates side-effects (likes, share) to a
 *    {@link PostActionListener} which will be implemented in the ViewModel/Fragment layer.
 *  • DiffUtil guarantees minimal UI updates, critical for large feeds or low-memory devices.
 */
public class PostAdapter extends ListAdapter<Post, PostAdapter.PostViewHolder> {

    /**
     * Callback interface exposed to consuming layer (Fragment/ViewModel).
     */
    public interface PostActionListener {
        void onPostSelected(@NonNull Post post);
        void onLikeToggled(@NonNull Post post);
        void onCommentRequested(@NonNull Post post);
        void onShareRequested(@NonNull Post post);
        void onRetrySyncRequested(@NonNull Post post);
    }

    private final RequestManager imageLoader;
    private final PostActionListener listener;

    public PostAdapter(@NonNull RequestManager imageLoader,
                       @NonNull PostActionListener listener) {
        super(DIFF_CALLBACK);
        this.imageLoader = Preconditions.checkNotNull(imageLoader, "imageLoader");
        this.listener = Preconditions.checkNotNull(listener, "listener");
    }

    //region Adapter overrides ----------------------------------------------------------------------------------------

    @NonNull
    @Override
    public PostViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        final View itemView = LayoutInflater.from(parent.getContext())
                .inflate(R.layout.item_feed_post, parent, false);
        return new PostViewHolder(itemView);
    }

    @Override
    public void onBindViewHolder(@NonNull PostViewHolder holder, int position) {
        final Post post = getItem(position);
        holder.bind(post);
    }

    //endregion

    //region ViewHolder -----------------------------------------------------------------------------------------------

    final class PostViewHolder extends RecyclerView.ViewHolder {

        private final ImageView    avatarIv;
        private final TextView     authorTv;
        private final TextView     timestampTv;
        private final TextView     bodyTv;
        private final ImageView    mediaIv;
        private final ImageButton  likeBtn;
        private final ImageButton  commentBtn;
        private final ImageButton  shareBtn;
        private final ImageView    unsyncedIv;

        PostViewHolder(@NonNull View itemView) {
            super(itemView);
            avatarIv    = itemView.findViewById(R.id.post_avatar);
            authorTv    = itemView.findViewById(R.id.post_author);
            timestampTv = itemView.findViewById(R.id.post_timestamp);
            bodyTv      = itemView.findViewById(R.id.post_body);
            mediaIv     = itemView.findViewById(R.id.post_media);
            likeBtn     = itemView.findViewById(R.id.post_like_button);
            commentBtn  = itemView.findViewById(R.id.post_comment_button);
            shareBtn    = itemView.findViewById(R.id.post_share_button);
            unsyncedIv  = itemView.findViewById(R.id.post_unsynced_indicator);
        }

        void bind(@NonNull final Post post) {
            // Avatar ---------------------------------------------------------------------------
            imageLoader
                    .load(post.getAuthorAvatarUrl())
                    .placeholder(R.drawable.ic_avatar_placeholder)
                    .error(R.drawable.ic_avatar_placeholder)
                    .circleCrop()
                    .into(avatarIv);

            // Author & timestamp ---------------------------------------------------------------
            authorTv.setText(post.getAuthorName());

            CharSequence relTime =
                    DateUtils.getRelativeTimeSpanString(
                            post.getCreatedAt().getTime(),
                            System.currentTimeMillis(),
                            DateUtils.MINUTE_IN_MILLIS,
                            DateUtils.FORMAT_ABBREV_ALL);
            timestampTv.setText(relTime);

            // Body -----------------------------------------------------------------------------            
            bodyTv.setText(post.getBody());

            // Media (image / video thumbnail) --------------------------------------------------
            if (post.hasMedia()) {
                mediaIv.setVisibility(View.VISIBLE);
                imageLoader
                        .load(post.getMediaThumbnailUrl())
                        .placeholder(R.drawable.ic_image_placeholder)
                        .error(R.drawable.ic_broken_image)
                        .into(mediaIv);
            } else {
                mediaIv.setVisibility(View.GONE);
            }

            // Like button state ----------------------------------------------------------------
            likeBtn.setImageResource(post.isLiked()
                    ? R.drawable.ic_favorite_filled_24
                    : R.drawable.ic_favorite_border_24);

            // Color tint depending on like state
            int tintColor = post.isLiked()
                    ? ContextCompat.getColor(itemView.getContext(), R.color.favoriteEnabled)
                    : ContextCompat.getColor(itemView.getContext(), R.color.favoriteDisabled);
            likeBtn.setImageTintList(ColorStateList.valueOf(tintColor));

            // Offline / unsynced indicator -----------------------------------------------------
            if (post.isPendingSync()) {
                unsyncedIv.setVisibility(View.VISIBLE);
                unsyncedIv.setContentDescription(
                        itemView.getContext().getString(R.string.feed_unsynced_content_description));
            } else {
                unsyncedIv.setVisibility(View.GONE);
            }

            // Click listeners ------------------------------------------------------------------
            itemView.setOnClickListener(v -> listener.onPostSelected(post));

            likeBtn.setOnClickListener(v -> {
                // Guard against quick double taps while offline
                if (!NetworkUtil.isOnline(v.getContext()) && !post.isLiked()) {
                    unsyncedIv.setVisibility(View.VISIBLE); // user feedback
                }
                listener.onLikeToggled(post);
            });

            commentBtn.setOnClickListener(v -> listener.onCommentRequested(post));
            shareBtn.setOnClickListener(v -> listener.onShareRequested(post));
            mediaIv.setOnClickListener(v -> listener.onPostSelected(post));
            unsyncedIv.setOnClickListener(v -> listener.onRetrySyncRequested(post));
        }
    }

    //endregion

    //region DiffUtil --------------------------------------------------------------------------------------------------

    private static final DiffUtil.ItemCallback<Post> DIFF_CALLBACK =
            new DiffUtil.ItemCallback<Post>() {
                @Override
                public boolean areItemsTheSame(@NonNull Post oldItem, @NonNull Post newItem) {
                    // Unique identifier
                    return oldItem.getId().equals(newItem.getId());
                }

                @Override
                public boolean areContentsTheSame(@NonNull Post oldItem, @NonNull Post newItem) {
                    // Rely on overridden equals for deep comparison
                    return oldItem.equals(newItem);
                }
            };

    //endregion

    //region Public helpers --------------------------------------------------------------------------------------------

    /**
     * Updates the adapter list with new data in a thread-safe way.
     * This method is a thin wrapper around {@link #submitList(java.util.List)} with null-safe copy.
     */
    public void update(java.util.List<Post> newPosts) {
        submitList(newPosts == null ? java.util.Collections.emptyList() :
                    java.util.Collections.unmodifiableList(newPosts));
    }

    //endregion
}
```
