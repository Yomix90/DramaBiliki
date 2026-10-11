import 'episode.dart';

class SeriesModel {
  final int id;
  final String sourceId;
  final String slug;
  final String title;
  final String coverUrl;
  final String platform;
  final int totalEpisodes;
  final int availableEpisodes;
  final double rating;
  final List<String> genres;
  final bool isNew;
  final bool isPopular;

  SeriesModel({
    required this.id,
    required this.sourceId,
    required this.slug,
    required this.title,
    required this.coverUrl,
    required this.platform,
    required this.totalEpisodes,
    required this.availableEpisodes,
    required this.rating,
    required this.genres,
    required this.isNew,
    required this.isPopular,
  });

  factory SeriesModel.fromJson(Map<String, dynamic> json) {
    final rawGenres = json['genres'] as List<dynamic>? ?? [];
    return SeriesModel(
      id: json['id'] as int? ?? 0,
      sourceId: json['source_id']?.toString() ?? '',
      slug: json['slug'] as String? ?? '',
      title: json['title'] as String? ?? '',
      coverUrl: json['cover_url'] as String? ?? '',
      platform: json['platform'] as String? ?? '',
      totalEpisodes: json['total_episodes'] as int? ?? 0,
      availableEpisodes: json['available_episodes'] as int? ?? 0,
      rating: (json['rating'] as num?)?.toDouble() ?? 4.8,
      genres: rawGenres.map((e) => e.toString()).toList(),
      isNew: json['is_new'] as bool? ?? false,
      isPopular: json['is_popular'] as bool? ?? false,
    );
  }
}

class SeriesDetailModel extends SeriesModel {
  final String description;
  final List<EpisodeModel> episodes;
  final bool isFavorite;
  final int? lastWatchedEpisode;
  final int? lastPositionSeconds;

  SeriesDetailModel({
    required super.id,
    required super.sourceId,
    required super.slug,
    required super.title,
    required super.coverUrl,
    required super.platform,
    required super.totalEpisodes,
    required super.availableEpisodes,
    required super.rating,
    required super.genres,
    required super.isNew,
    required super.isPopular,
    required this.description,
    required this.episodes,
    required this.isFavorite,
    this.lastWatchedEpisode,
    this.lastPositionSeconds,
  });

  factory SeriesDetailModel.fromJson(Map<String, dynamic> json) {
    final rawGenres = json['genres'] as List<dynamic>? ?? [];
    final rawEpisodes = json['episodes'] as List<dynamic>? ?? [];

    return SeriesDetailModel(
      id: json['id'] as int? ?? 0,
      sourceId: json['source_id']?.toString() ?? '',
      slug: json['slug'] as String? ?? '',
      title: json['title'] as String? ?? '',
      coverUrl: json['cover_url'] as String? ?? '',
      platform: json['platform'] as String? ?? '',
      totalEpisodes: json['total_episodes'] as int? ?? 0,
      availableEpisodes: json['available_episodes'] as int? ?? 0,
      rating: (json['rating'] as num?)?.toDouble() ?? 4.8,
      genres: rawGenres.map((e) => e.toString()).toList(),
      isNew: json['is_new'] as bool? ?? false,
      isPopular: json['is_popular'] as bool? ?? false,
      description: json['description'] as String? ?? '',
      episodes: rawEpisodes.map((e) => EpisodeModel.fromJson(e as Map<String, dynamic>)).toList(),
      isFavorite: json['is_favorite'] as bool? ?? false,
      lastWatchedEpisode: json['last_watched_episode'] as int?,
      lastPositionSeconds: json['last_position_seconds'] as int?,
    );
  }
}
