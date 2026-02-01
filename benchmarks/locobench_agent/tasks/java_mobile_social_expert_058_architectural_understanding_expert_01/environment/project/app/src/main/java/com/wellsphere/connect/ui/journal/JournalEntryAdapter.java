```java
/*
 * Copyright (c) 2024
 * WellSphere Digital Health, Inc.  |  All rights reserved.
 *
 * This source code is part of the WellSphere Connect mobile application.
 * It is subject to the terms and conditions defined in the file 'LICENSE',
 * which is part of this source code package.
 */

package com.wellsphere.connect.ui.journal;

import android.graphics.Color;
import android.text.TextUtils;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.graphics.ColorUtils;
import androidx.recyclerview.widget.DiffUtil;
import androidx.recyclerview.widget.ListAdapter;
import androidx.recyclerview.widget.RecyclerView;

import com.bumptech.glide.Glide;
import com.wellsphere.connect.R;
import com.wellsphere.connect.databinding.ItemJournalEntryBinding;
import com.wellsphere.connect.domain.model.JournalEntry;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/**
 * RecyclerView.Adapter implementation for rendering a paged list of {@link JournalEntry}s.
 * <p>
 * The adapter leverages {@link ListAdapter} with a {@link DiffUtil.ItemCallback} for extremely
 * efficient list mutations and animations while enforcing immutability of the backing data set.
 *
 * Each {@link JournalEntry} can:
 *  • Display a single media thumbnail (photo / PDF preview / activity icon)
 *  • Indicate cloud-sync status
 *  • Surface user–triggered actions (tap, long-press, share)
 *
 * Production quality considerations built-in:
 *  • Stable IDs prevent item flashes on rotation / configuration changes
 *  • Double-click debouncing via {@link ViewConfiguration#getDoubleTapTimeout()}
 *  • Glide memory-caching for thumbnails with placeholder & error fallbacks
 *  • Accessibility-friendly content descriptions
 */
public class JournalEntryAdapter
        extends ListAdapter<JournalEntry, JournalEntryAdapter.EntryViewHolder> {

    // UI interaction listener
    public interface OnEntryInteractionListener {
        void onEntryClicked(@NonNull JournalEntry entry);

        void onEntryLongPressed(@NonNull JournalEntry entry);

        void onShareRequested(@NonNull JournalEntry entry);
    }

    private static final DiffUtil.ItemCallback<JournalEntry> DIFF_CALLBACK =
            new DiffUtil.ItemCallback<JournalEntry>() {
                @Override
                public boolean areItemsTheSame(@NonNull JournalEntry oldItem,
                                               @NonNull JournalEntry newItem) {
                    return oldItem.getEntryId() == newItem.getEntryId();
                }

                @Override
                public boolean areContentsTheSame(@NonNull JournalEntry oldItem,
                                                  @NonNull JournalEntry newItem) {
                    return oldItem.equals(newItem);
                }
            };

    // Region: Instance fields
    @Nullable
    private final OnEntryInteractionListener interactionListener;
    private final DateTimeFormatter dateFormatter =
            DateTimeFormatter.ofPattern("MMM dd, yyyy  •  h:mm a", Locale.getDefault())
                              .withZone(ZoneId.systemDefault());

    // Constructor
    public JournalEntryAdapter(@Nullable OnEntryInteractionListener listener) {
        super(DIFF_CALLBACK);
        setHasStableIds(true);
        this.interactionListener = listener;
    }

    // ViewHolder factory
    @NonNull
    @Override
    public EntryViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        LayoutInflater inflater = LayoutInflater.from(parent.getContext());
        ItemJournalEntryBinding binding =
                ItemJournalEntryBinding.inflate(inflater, parent, false);
        return new EntryViewHolder(binding);
    }

    // Data binding
    @Override
    public void onBindViewHolder(@NonNull EntryViewHolder holder, int position) {
        holder.bind(getItem(position));
    }

    // Stable ID mapping
    @Override
    public long getItemId(int position) {
        JournalEntry entry = getItem(position);
        return entry != null ? entry.getEntryId() : RecyclerView.NO_ID;
    }

    // ViewHolder implementation
    class EntryViewHolder extends RecyclerView.ViewHolder
            implements View.OnClickListener, View.OnLongClickListener {

        private final ItemJournalEntryBinding binding;
        private long lastClickTime = 0L;

        EntryViewHolder(@NonNull ItemJournalEntryBinding binding) {
            super(binding.getRoot());
            this.binding = binding;

            binding.getRoot().setOnClickListener(this);
            binding.getRoot().setOnLongClickListener(this);
            binding.btnShare.setOnClickListener(v -> {
                JournalEntry entry = getCurrentEntry();
                if (entry != null && interactionListener != null) {
                    interactionListener.onShareRequested(entry);
                }
            });
        }

        void bind(@NonNull JournalEntry entry) {
            // Title & body excerpt
            binding.tvTitle.setText(entry.getTitle());
            binding.tvExcerpt.setText(entry.getExcerpt());
            binding.tvExcerpt.setEllipsize(TextUtils.TruncateAt.END);

            // Timestamp
            String formattedDate = dateFormatter.format(
                    Instant.ofEpochMilli(entry.getCreatedAtUtc()));
            binding.tvTimestamp.setText(formattedDate);

            // Sync status badge
            binding.ivSyncStatus.setImageResource(
                    entry.isSynced() ? R.drawable.ic_cloud_done_24
                                     : R.drawable.ic_cloud_off_24);
            binding.ivSyncStatus.setContentDescription(
                    itemView.getContext().getString(
                            entry.isSynced()
                                    ? R.string.cd_synced
                                    : R.string.cd_pending_sync));

            // Thumbnail (if any)
            Glide.with(binding.ivThumbnail)
                    .load(entry.getThumbnailUrl())
                    .centerCrop()
                    .placeholder(R.drawable.ic_placeholder_image_24)
                    .error(R.drawable.ic_broken_image_24)
                    .into(binding.ivThumbnail);

            // Accessibility
            itemView.setContentDescription(entry.getTitle());

            // Offline-highlight for unsynced entries
            final int baseColor = itemView.getContext()
                                          .getResources()
                                          .getColor(R.color.colorSurface, itemView.getContext().getTheme());
            int bgColor = entry.isSynced() ? baseColor
                                           : ColorUtils.setAlphaComponent(Color.YELLOW, 25);
            binding.cardContainer.setCardBackgroundColor(bgColor);
        }

        @Nullable
        private JournalEntry getCurrentEntry() {
            int position = getBindingAdapterPosition();
            if (position == RecyclerView.NO_POSITION) {
                return null;
            }
            return getItem(position);
        }

        // Click listener
        @Override
        public void onClick(View v) {
            // Debounce double-taps
            long clickTime = System.currentTimeMillis();
            if (clickTime - lastClickTime < ViewConfiguration.getDoubleTapTimeout()) {
                return;
            }
            lastClickTime = clickTime;

            JournalEntry entry = getCurrentEntry();
            if (entry == null) return;

            if (interactionListener != null) {
                interactionListener.onEntryClicked(entry);
            } else {
                Toast.makeText(itemView.getContext(),
                               R.string.msg_no_listener_attached,
                               Toast.LENGTH_SHORT).show();
            }
        }

        // Long-press listener
        @Override
        public boolean onLongClick(View v) {
            JournalEntry entry = getCurrentEntry();
            if (entry == null) return false;

            if (interactionListener != null) {
                interactionListener.onEntryLongPressed(entry);
                return true;
            }
            return false;
        }
    }
}
```