class EpisodeModel {
  final int id;
  final int num;
  final String title;
  final int duration;
  final String? thumbnailUrl;
  final bool isFree;
  final bool isWatched;
  final int watchedSeconds;

  EpisodeModel({
    required this.id,
    required this.num,
    required this.title,
    required this.duration,
    this.thumbnailUrl,
    required this.isFree,
    required this.isWatched,
    required this.watchedSeconds,
  });

  factory EpisodeModel.fromJson(Map<String, dynamic> json) {
    return EpisodeModel(
      id: json['id'] as int? ?? 0,
      num: json['num'] as int? ?? 1,
      title: json['title'] as String? ?? 'Episode',
      duration: json['duration'] as int? ?? 120,
      thumbnailUrl: json['thumbnail_url'] as String?,
      isFree: json['is_free'] as bool? ?? true,
      isWatched: json['is_watched'] as bool? ?? false,
      watchedSeconds: json['watched_seconds'] as int? ?? 0,
    );
  }
}
