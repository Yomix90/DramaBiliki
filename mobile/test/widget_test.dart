import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/localization.dart';
import 'package:mobile/models/series.dart';
import 'package:mobile/models/episode.dart';
import 'package:mobile/models/library.dart';
import 'package:mobile/widgets/network_cover.dart';
import 'package:mobile/widgets/series_card.dart';

void main() {
  group('Localization tests', () {
    test('Translates keys properly in EN, FR, AR', () {
      final en = AppLocale('en');
      final fr = AppLocale('fr');
      final ar = AppLocale('ar');

      expect(en.t('trending_now'), 'Trending Now');
      expect(fr.t('trending_now'), 'Tendances du moment');
      expect(ar.t('trending_now'), 'الأكثر تداولاً');

      // Unknown keys fall back to English, then to the key itself.
      expect(AppLocale('xx').t('tab_home'), 'Home');
      expect(en.t('missing_key'), 'missing_key');

      expect(en.isRTL, false);
      expect(fr.isRTL, false);
      expect(ar.isRTL, true);
    });
  });

  group('Localization parity', () {
    test('FR and AR define every EN key', () {
      final en = AppLocale('en');
      for (final lang in ['fr', 'ar']) {
        final other = AppLocale(lang);
        for (final key in AppLocale.keysFor('en')) {
          expect(AppLocale.keysFor(lang), contains(key), reason: '$lang is missing "$key"');
          expect(other.t(key).isNotEmpty, true);
        }
      }
      expect(en.t('tab_for_you'), 'For You');
    });
  });

  group('Library model', () {
    test('keeps only the latest history entry per series, newest first', () {
      final lib = LibraryModel.fromJson({
        'favorites': [
          {'id': 7, 'slug': 'a', 'title': 'A', 'cover_url': '', 'available_episodes': 30},
        ],
        'history': [
          {'series_id': 1, 'title': 'One', 'episode_num': 2, 'position_seconds': 50, 'total_seconds': 100, 'updated_at': '2026-10-01T10:00:00'},
          {'series_id': 1, 'title': 'One', 'episode_num': 5, 'position_seconds': 10, 'total_seconds': 100, 'updated_at': '2026-10-03T10:00:00'},
          {'series_id': 2, 'title': 'Two', 'episode_num': 1, 'position_seconds': 30, 'total_seconds': 60, 'updated_at': '2026-10-02T10:00:00'},
        ],
      });

      expect(lib.favorites.single.id, 7);
      expect(lib.history.length, 2);
      expect(lib.history.first.seriesId, 1);
      expect(lib.history.first.episodeNum, 5);
      expect(lib.history.last.progress, closeTo(0.5, 0.001));
    });
  });

  group('Cover URLs', () {
    test('requests resized variants only for local bridge covers', () {
      expect(sizedCoverUrl('http://h/media/covers/1.webp', width: 200), 'http://h/media/covers/1.webp?w=300');
      expect(sizedCoverUrl('http://h/media/covers/1.webp', width: 500), 'http://h/media/covers/1.webp?w=600');
      expect(sizedCoverUrl('https://cdn.example.com/x.jpg', width: 300), 'https://cdn.example.com/x.jpg');
      expect(sizedCoverUrl('', width: 300), '');
    });
  });

  group('Data model tests', () {
    test('SeriesModel and EpisodeModel deserialize correctly from JSON', () {
      final seriesJson = {
        'id': 101,
        'source_id': '319823',
        'slug': 'sample-drama',
        'title': 'Alpha Love Story',
        'cover_url': 'https://example.com/cover.webp',
        'platform': 'DramaBox',
        'total_episodes': 50,
        'available_episodes': 48,
        'rating': 4.9,
        'genres': ['Romance', 'Werewolf'],
        'is_new': true,
        'is_popular': false,
      };

      final series = SeriesModel.fromJson(seriesJson);
      expect(series.id, 101);
      expect(series.sourceId, '319823');
      expect(series.title, 'Alpha Love Story');
      expect(series.availableEpisodes, 48);
      expect(series.genres.length, 2);

      final episodeJson = {
        'id': 1,
        'num': 2,
        'title': 'Episode 2',
        'duration': 140,
        'is_free': true,
        'is_watched': true,
        'watched_seconds': 140,
      };

      final ep = EpisodeModel.fromJson(episodeJson);
      expect(ep.num, 2);
      expect(ep.duration, 140);
      expect(ep.isWatched, true);
    });
  });

  group('Widget rendering tests', () {
    testWidgets('SeriesCard displays title and episode pill', (WidgetTester tester) async {
      final testSeries = SeriesModel(
        id: 1,
        sourceId: '123',
        slug: 'test-slug',
        title: 'Billionaire Return',
        coverUrl: 'https://example.com/cover.jpg',
        platform: 'ShortMax',
        totalEpisodes: 60,
        availableEpisodes: 60,
        rating: 4.8,
        genres: ['Drama'],
        isNew: true,
        isPopular: true,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 130,
              child: SeriesCard(
                series: testSeries,
                onTap: () {},
              ),
            ),
          ),
        ),
      );

      expect(find.text('Billionaire Return'), findsOneWidget);
      expect(find.text('60 EP'), findsOneWidget);
      expect(find.text('HOT'), findsOneWidget);
      expect(find.text('ShortMax'), findsOneWidget);
    });
  });
}
