import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/app_theme.dart';
import '../../core/localization.dart';
import '../../core/navigation.dart';
import '../../models/series.dart';
import '../../providers/app_providers.dart';
import '../../widgets/network_cover.dart';
import '../../widgets/series_card.dart';
import '../../widgets/shimmer_loading.dart';
import '../../widgets/state_views.dart';

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final TextEditingController _controller = TextEditingController();
  final FocusNode _focus = FocusNode();
  Timer? _debounce;

  /// Text being typed (drives suggestions).
  String _typing = '';

  /// Submitted query (drives results).
  String _query = '';

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      if (!mounted) return;
      setState(() {
        _typing = value.trim();
        if (_typing.isEmpty) _query = '';
      });
    });
  }

  void _submit(String value) {
    final q = value.trim();
    if (q.isEmpty) return;
    _debounce?.cancel();
    _controller.text = q;
    _controller.selection = TextSelection.collapsed(offset: q.length);
    _focus.unfocus();
    ref.read(recentSearchesProvider.notifier).add(q);
    setState(() {
      _typing = q;
      _query = q;
    });
  }

  void _clear() {
    _controller.clear();
    _focus.requestFocus();
    setState(() {
      _typing = '';
      _query = '';
    });
  }

  @override
  Widget build(BuildContext context) {
    final loc = AppLocale(ref.watch(localeProvider));

    Widget body;
    if (_query.isNotEmpty && _query == _typing) {
      body = _Results(query: _query, loc: loc);
    } else if (_typing.isNotEmpty) {
      body = _Suggestions(query: _typing, onPick: _submit);
    } else {
      body = _Discover(loc: loc, onPick: _submit);
    }

    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        titleSpacing: 0,
        title: Padding(
          padding: const EdgeInsetsDirectional.only(end: 16),
          child: SizedBox(
            height: 40,
            child: TextField(
              controller: _controller,
              focusNode: _focus,
              autofocus: true,
              textInputAction: TextInputAction.search,
              onChanged: _onChanged,
              onSubmitted: _submit,
              style: const TextStyle(color: Colors.white, fontSize: 15),
              decoration: InputDecoration(
                hintText: loc.t('search_hint'),
                prefixIcon: const Icon(Icons.search_rounded, color: AppTheme.textMuted, size: 20),
                suffixIcon: ListenableBuilder(
                  listenable: _controller,
                  builder: (context, _) => _controller.text.isEmpty
                      ? const SizedBox.shrink()
                      : IconButton(
                          icon: const Icon(Icons.cancel_rounded, color: AppTheme.textMuted, size: 18),
                          onPressed: _clear,
                        ),
                ),
                contentPadding: EdgeInsets.zero,
              ),
            ),
          ),
        ),
      ),
      body: body,
    );
  }
}

class _Discover extends ConsumerWidget {
  final AppLocale loc;
  final ValueChanged<String> onPick;

  const _Discover({required this.loc, required this.onPick});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final recent = ref.watch(recentSearchesProvider);
    final feed = ref.watch(homeFeedProvider).value;
    final hot = feed == null || feed.sections.isEmpty ? const <SeriesModel>[] : feed.sections.first.series.take(10).toList();

    return ListView(
      padding: const EdgeInsets.symmetric(vertical: 8),
      children: [
        if (recent.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsetsDirectional.only(start: 16, end: 4),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    loc.t('recent_searches'),
                    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
                  ),
                ),
                IconButton(
                  tooltip: loc.t('clear'),
                  icon: const Icon(Icons.delete_outline_rounded, color: AppTheme.textMuted, size: 20),
                  onPressed: () => ref.read(recentSearchesProvider.notifier).clear(),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final q in recent)
                  ActionChip(
                    label: Text(q),
                    onPressed: () => onPick(q),
                    backgroundColor: AppTheme.surfaceLight,
                    side: BorderSide.none,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                    labelStyle: const TextStyle(color: AppTheme.textSecondary, fontSize: 13),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
        if (hot.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
            child: Text(
              '🔥 ${loc.t('hot_searches')}',
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
            ),
          ),
          for (var i = 0; i < hot.length; i++) _HotRow(rank: i + 1, series: hot[i], loc: loc),
        ],
      ],
    );
  }
}

class _HotRow extends StatelessWidget {
  final int rank;
  final SeriesModel series;
  final AppLocale loc;

  const _HotRow({required this.rank, required this.series, required this.loc});

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => openSeries(context, series.slug),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        child: Row(
          children: [
            SizedBox(
              width: 28,
              child: Text(
                '$rank',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                  fontStyle: FontStyle.italic,
                  color: rank <= 3 ? AppTheme.rankColors[rank - 1] : AppTheme.textMuted,
                ),
              ),
            ),
            NetworkCover(url: series.coverUrl, width: 48, height: 64, borderRadius: BorderRadius.circular(6)),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    series.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    [
                      "${series.availableEpisodes} ${loc.t('ep')}",
                      ...series.genres.take(2),
                    ].join(' · '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: AppTheme.textMuted, fontSize: 12),
                  ),
                ],
              ),
            ),
            if (series.isPopular) const Icon(Icons.local_fire_department_rounded, color: AppTheme.primary, size: 18),
          ],
        ),
      ),
    );
  }
}

class _Suggestions extends ConsumerWidget {
  final String query;
  final ValueChanged<String> onPick;

  const _Suggestions({required this.query, required this.onPick});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final suggestions = ref.watch(searchSuggestionsProvider(query)).value ?? const <String>[];
    final items = [query, ...suggestions.where((s) => s.toLowerCase() != query.toLowerCase())];

    return ListView.builder(
      itemCount: items.length,
      itemBuilder: (context, i) {
        final text = items[i];
        return ListTile(
          leading: const Icon(Icons.search_rounded, color: AppTheme.textMuted, size: 20),
          title: _highlight(text, query),
          trailing: const Icon(Icons.north_west_rounded, color: AppTheme.textMuted, size: 16),
          onTap: () => onPick(text),
        );
      },
    );
  }

  Widget _highlight(String text, String query) {
    final idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx < 0) return Text(text, maxLines: 1, overflow: TextOverflow.ellipsis);
    return Text.rich(
      TextSpan(children: [
        TextSpan(text: text.substring(0, idx)),
        TextSpan(
          text: text.substring(idx, idx + query.length),
          style: const TextStyle(color: AppTheme.primary, fontWeight: FontWeight.w700),
        ),
        TextSpan(text: text.substring(idx + query.length)),
      ]),
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
    );
  }
}

class _Results extends ConsumerWidget {
  final String query;
  final AppLocale loc;

  const _Results({required this.query, required this.loc});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final resultsAsync = ref.watch(searchResultsProvider(query));

    return resultsAsync.when(
      loading: () => const ShimmerGrid(),
      error: (_, _) => ErrorView(
        message: loc.t('load_error'),
        retryLabel: loc.t('retry'),
        onRetry: () => ref.invalidate(searchResultsProvider(query)),
      ),
      data: (results) {
        if (results.isEmpty) {
          return EmptyView(icon: Icons.search_off_rounded, message: loc.t('no_results'));
        }
        return GridView.builder(
          padding: const EdgeInsets.all(16),
          gridDelegate: posterGridDelegate,
          itemCount: results.length,
          itemBuilder: (context, i) {
            final s = results[i];
            return SeriesCard(
              series: s,
              episodesLabel: loc.t('ep'),
              badgeHot: loc.t('hot'),
              badgeNew: loc.t('new_badge'),
              onTap: () => openSeries(context, s.slug),
            );
          },
        );
      },
    );
  }
}
