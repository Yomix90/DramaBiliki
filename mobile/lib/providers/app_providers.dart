import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/api_client.dart';
import '../core/constants.dart';
import '../core/preferences.dart';
import '../core/repository.dart';
import '../models/account.dart';
import '../models/genre.dart';
import '../models/home_feed.dart';
import '../models/library.dart';
import '../models/series.dart';

// Service providers (preferences is overridden in main.dart)
final preferencesProvider = Provider<PreferencesService>((ref) {
  throw UnimplementedError();
});

final apiClientProvider = Provider<ApiClient>((ref) {
  final prefs = ref.watch(preferencesProvider);
  return ApiClient(prefs);
});

final repositoryProvider = Provider<DramaRepository>((ref) {
  return DramaRepository(ref.watch(apiClientProvider));
});

// ---------------------------------------------------------------------------
// Locale & settings
// ---------------------------------------------------------------------------

class LocaleNotifier extends Notifier<String> {
  @override
  String build() {
    final prefs = ref.watch(preferencesProvider);
    return prefs.getLanguage();
  }

  Future<void> setLocale(String langCode) async {
    final prefs = ref.read(preferencesProvider);
    await prefs.setLanguage(langCode);
    state = langCode;
  }
}

final localeProvider = NotifierProvider<LocaleNotifier, String>(LocaleNotifier.new);

class PlaybackSettings {
  final bool dataSaver;
  final bool autoplayNext;
  final bool subtitles;

  const PlaybackSettings({required this.dataSaver, required this.autoplayNext, required this.subtitles});

  PlaybackSettings copyWith({bool? dataSaver, bool? autoplayNext, bool? subtitles}) {
    return PlaybackSettings(
      dataSaver: dataSaver ?? this.dataSaver,
      autoplayNext: autoplayNext ?? this.autoplayNext,
      subtitles: subtitles ?? this.subtitles,
    );
  }
}

class SettingsNotifier extends Notifier<PlaybackSettings> {
  @override
  PlaybackSettings build() {
    final prefs = ref.watch(preferencesProvider);
    return PlaybackSettings(
      dataSaver: prefs.getDataSaver(),
      autoplayNext: prefs.getAutoplayNext(),
      subtitles: prefs.getSubtitlesEnabled(),
    );
  }

  void setDataSaver(bool value) {
    ref.read(preferencesProvider).setDataSaver(value);
    state = state.copyWith(dataSaver: value);
  }

  void setAutoplayNext(bool value) {
    ref.read(preferencesProvider).setAutoplayNext(value);
    state = state.copyWith(autoplayNext: value);
  }

  void setSubtitles(bool value) {
    ref.read(preferencesProvider).setSubtitlesEnabled(value);
    state = state.copyWith(subtitles: value);
  }
}

final settingsProvider = NotifierProvider<SettingsNotifier, PlaybackSettings>(SettingsNotifier.new);

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

final authInitProvider = FutureProvider<bool>((ref) async {
  final api = ref.watch(apiClientProvider);
  final existingToken = api.preferences.getAuthToken();
  if (existingToken != null && existingToken.isNotEmpty) {
    return true;
  }
  return await api.authenticateDevice() != null;
});

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

final homeFeedProvider = FutureProvider<HomeFeedModel>((ref) async {
  ref.watch(localeProvider);
  return ref.watch(repositoryProvider).getHomeFeed();
});

final genresProvider = FutureProvider<List<GenreModel>>((ref) async {
  ref.watch(localeProvider);
  return ref.watch(repositoryProvider).getGenres();
});

final seriesDetailProvider = FutureProvider.autoDispose.family<SeriesDetailModel, String>((ref, idOrSlug) async {
  ref.watch(localeProvider);
  return ref.watch(repositoryProvider).getSeriesDetail(idOrSlug);
});

/// A page-by-page list of series, used by the genre tabs and the For You feed.
class PagedSeries {
  final List<SeriesModel> items;
  final int page;
  final bool hasMore;
  final bool isLoadingMore;

  const PagedSeries({required this.items, required this.page, required this.hasMore, this.isLoadingMore = false});

  PagedSeries copyWith({List<SeriesModel>? items, int? page, bool? hasMore, bool? isLoadingMore}) {
    return PagedSeries(
      items: items ?? this.items,
      page: page ?? this.page,
      hasMore: hasMore ?? this.hasMore,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
    );
  }
}

class PagedSeriesNotifier extends AsyncNotifier<PagedSeries> {
  PagedSeriesNotifier(this.genre);

  /// Genre slug, or empty for the whole catalog.
  final String genre;

  @override
  Future<PagedSeries> build() async {
    ref.watch(localeProvider);
    final items = await ref.watch(repositoryProvider).listSeries(genre: genre, limit: AppConstants.pageSize);
    return PagedSeries(items: items, page: 1, hasMore: items.length >= AppConstants.pageSize);
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.isLoadingMore) return;

    state = AsyncData(current.copyWith(isLoadingMore: true));
    try {
      final next = await ref
          .read(repositoryProvider)
          .listSeries(genre: genre, page: current.page + 1, limit: AppConstants.pageSize);
      final known = current.items.map((s) => s.id).toSet();
      state = AsyncData(current.copyWith(
        items: [...current.items, ...next.where((s) => !known.contains(s.id))],
        page: current.page + 1,
        hasMore: next.length >= AppConstants.pageSize,
        isLoadingMore: false,
      ));
    } catch (_) {
      state = AsyncData(current.copyWith(isLoadingMore: false));
    }
  }
}

final pagedSeriesProvider =
    AsyncNotifierProvider.family<PagedSeriesNotifier, PagedSeries, String>(PagedSeriesNotifier.new);

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

final searchResultsProvider = FutureProvider.autoDispose.family<List<SeriesModel>, String>((ref, query) async {
  return ref.watch(repositoryProvider).listSeries(query: query, limit: 30);
});

final searchSuggestionsProvider = FutureProvider.autoDispose.family<List<String>, String>((ref, query) async {
  return ref.watch(repositoryProvider).suggest(query);
});

class RecentSearchesNotifier extends Notifier<List<String>> {
  static const _maxItems = 10;

  @override
  List<String> build() => ref.watch(preferencesProvider).getRecentSearches();

  void add(String query) {
    final q = query.trim();
    if (q.isEmpty) return;
    final updated = [q, ...state.where((s) => s.toLowerCase() != q.toLowerCase())].take(_maxItems).toList();
    state = updated;
    ref.read(preferencesProvider).setRecentSearches(updated);
  }

  void clear() {
    state = const [];
    ref.read(preferencesProvider).setRecentSearches(const []);
  }
}

final recentSearchesProvider = NotifierProvider<RecentSearchesNotifier, List<String>>(RecentSearchesNotifier.new);

// ---------------------------------------------------------------------------
// Library & favorites
// ---------------------------------------------------------------------------

final libraryProvider = FutureProvider<LibraryModel>((ref) async {
  ref.watch(localeProvider);
  return ref.watch(repositoryProvider).getLibrary();
});

/// Optimistic favorite states set in this session, keyed by series id.
/// Screens read `overrides[id] ?? valueFromServer`.
class FavoritesNotifier extends Notifier<Map<int, bool>> {
  @override
  Map<int, bool> build() => const {};

  /// Sets the favorite state and returns the state actually persisted.
  Future<bool> setFavorite(int seriesId, bool favorite) async {
    state = {...state, seriesId: favorite};
    try {
      await ref.read(repositoryProvider).setFavorite(seriesId, favorite);
      ref.invalidate(libraryProvider);
      return favorite;
    } catch (_) {
      state = {...state, seriesId: !favorite};
      return !favorite;
    }
  }
}

final favoritesProvider = NotifierProvider<FavoritesNotifier, Map<int, bool>>(FavoritesNotifier.new);

/// Refreshes everything that depends on watch progress (call after leaving the player).
void refreshWatchState(WidgetRef ref) {
  ref.invalidate(homeFeedProvider);
  ref.invalidate(libraryProvider);
  ref.invalidate(seriesDetailProvider);
}

// ---------------------------------------------------------------------------
// Account, ads
// ---------------------------------------------------------------------------

/// Current user's profile (guest or registered); null when the server is unreachable.
final accountProvider = FutureProvider<UserProfile?>((ref) async {
  try {
    return await ref.watch(repositoryProvider).me();
  } catch (_) {
    return null;
  }
});

final adsConfigProvider = FutureProvider<AdsConfig>((ref) async {
  ref.watch(accountProvider); // ad-free accounts change the answer
  try {
    return await ref.watch(repositoryProvider).adsConfig();
  } catch (_) {
    return AdsConfig.disabled;
  }
});

/// Reloads everything tied to the signed-in user (after login, register or logout).
void refreshSession(WidgetRef ref) {
  ref.invalidate(accountProvider);
  ref.invalidate(favoritesProvider);
  refreshWatchState(ref);
}
