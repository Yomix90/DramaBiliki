import 'package:flutter/foundation.dart';
import 'package:video_player/video_player.dart';

/// Owns the video controllers of a vertical feed: one controller per page key,
/// created on demand (current page + preloaded neighbours) and disposed as soon
/// as the page leaves the retained window.
class VideoPool {
  VideoPool({required this.onChanged});

  /// Called whenever a controller finishes initializing or fails, so the owner can rebuild.
  final VoidCallback onChanged;

  final Map<String, VideoPlayerController> _controllers = {};
  final Map<String, Future<VideoPlayerController?>> _inits = {};
  final Set<String> _errors = {};
  bool _disposed = false;

  VideoPlayerController? operator [](String key) {
    final c = _controllers[key];
    return (c != null && c.value.isInitialized) ? c : null;
  }

  bool hasError(String key) => _errors.contains(key);

  /// Creates (if needed) and initializes the controller for [key].
  /// Resolves to null when initialization fails or the key was evicted meanwhile.
  Future<VideoPlayerController?> ensure(
    String key,
    Uri uri, {
    Future<ClosedCaptionFile> Function()? captions,
  }) {
    final existing = _inits[key];
    if (existing != null) return existing;

    _errors.remove(key);
    final controller = VideoPlayerController.networkUrl(
      uri,
      closedCaptionFile: captions?.call(),
      videoPlayerOptions: VideoPlayerOptions(mixWithOthers: false),
    );
    _controllers[key] = controller;

    final future = controller.initialize().then<VideoPlayerController?>((_) {
      if (_disposed || _controllers[key] != controller) return null;
      _notify();
      return controller;
    }).catchError((Object e) {
      debugPrint('Video init failed for $key: $e');
      if (_disposed || _controllers[key] != controller) return null;
      _errors.add(key);
      _notify();
      return null;
    });
    _inits[key] = future;
    return future;
  }

  /// Drops a failed controller so the next [ensure] starts from scratch.
  void reset(String key) {
    _inits.remove(key);
    _errors.remove(key);
    _controllers.remove(key)?.dispose();
  }

  /// Disposes every controller whose key is not in [keep].
  void retain(Set<String> keep) {
    final evicted = _controllers.keys.where((k) => !keep.contains(k)).toList();
    for (final k in evicted) {
      reset(k);
    }
  }

  void pauseAll({String? except}) {
    _controllers.forEach((k, c) {
      if (k != except && c.value.isInitialized && c.value.isPlaying) c.pause();
    });
  }

  void dispose() {
    _disposed = true;
    for (final c in _controllers.values) {
      c.dispose();
    }
    _controllers.clear();
    _inits.clear();
  }

  void _notify() {
    if (!_disposed) onChanged();
  }
}
