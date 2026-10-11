import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';
import '../core/app_theme.dart';
import 'network_cover.dart';

/// Full-screen video layer: fills the screen for vertical videos (letterboxes
/// landscape ones), shows the cover until the first frame, a spinner while
/// buffering, subtitles, and an error state with retry.
class VideoSurface extends StatelessWidget {
  final VideoPlayerController? controller;
  final String posterUrl;
  final bool hasError;
  final bool showCaptions;
  final String errorText;
  final String retryText;
  final VoidCallback onRetry;

  /// Distance of the subtitles from the bottom edge.
  final double captionBottom;

  const VideoSurface({
    super.key,
    required this.controller,
    required this.posterUrl,
    required this.hasError,
    required this.showCaptions,
    required this.errorText,
    required this.retryText,
    required this.onRetry,
    this.captionBottom = 190,
  });

  @override
  Widget build(BuildContext context) {
    final c = controller;

    return Stack(
      fit: StackFit.expand,
      children: [
        if (c == null) ...[
          // Blurred-looking poster while loading
          Opacity(opacity: 0.45, child: NetworkCover(url: posterUrl, variantWidth: 600)),
          Center(
            child: hasError
                ? Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.error_outline_rounded, color: Colors.white70, size: 44),
                      const SizedBox(height: 10),
                      Text(errorText, style: const TextStyle(color: Colors.white70)),
                      const SizedBox(height: 14),
                      ElevatedButton.icon(
                        onPressed: onRetry,
                        icon: const Icon(Icons.refresh_rounded),
                        label: Text(retryText),
                      ),
                    ],
                  )
                : const CircularProgressIndicator(color: AppTheme.primary, strokeWidth: 2.5),
          ),
        ] else ...[
          _buildVideo(c),
          ValueListenableBuilder<VideoPlayerValue>(
            valueListenable: c,
            builder: (context, value, _) {
              return Stack(
                fit: StackFit.expand,
                children: [
                  if (value.isBuffering && value.isPlaying)
                    const Center(child: CircularProgressIndicator(color: Colors.white70, strokeWidth: 2.5)),
                  if (showCaptions && value.caption.text.isNotEmpty)
                    Positioned(
                      left: 24,
                      right: 24,
                      bottom: captionBottom,
                      child: Text(
                        value.caption.text,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 17,
                          fontWeight: FontWeight.w700,
                          height: 1.3,
                          shadows: [
                            Shadow(color: Colors.black, blurRadius: 4),
                            Shadow(color: Colors.black, blurRadius: 10),
                          ],
                        ),
                      ),
                    ),
                ],
              );
            },
          ),
        ],
      ],
    );
  }

  Widget _buildVideo(VideoPlayerController c) {
    final size = c.value.size;
    if (size.width <= 0 || size.height <= 0) {
      return Center(child: AspectRatio(aspectRatio: c.value.aspectRatio, child: VideoPlayer(c)));
    }
    final isPortrait = size.height >= size.width;
    return ClipRect(
      child: FittedBox(
        fit: isPortrait ? BoxFit.cover : BoxFit.contain,
        child: SizedBox(width: size.width, height: size.height, child: VideoPlayer(c)),
      ),
    );
  }
}

/// Thin progress bar that grows into a scrubber while dragging.
class VideoProgressBar extends StatefulWidget {
  final VideoPlayerController controller;

  const VideoProgressBar({super.key, required this.controller});

  @override
  State<VideoProgressBar> createState() => _VideoProgressBarState();
}

class _VideoProgressBarState extends State<VideoProgressBar> {
  double? _dragValue;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<VideoPlayerValue>(
      valueListenable: widget.controller,
      builder: (context, value, _) {
        final durMs = value.duration.inMilliseconds;
        final max = durMs > 0 ? durMs.toDouble() : 1.0;
        final current = (_dragValue ?? value.position.inMilliseconds.toDouble()).clamp(0.0, max);
        final dragging = _dragValue != null;

        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (dragging)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '${_fmt(Duration(milliseconds: current.toInt()))} / ${_fmt(value.duration)}',
                  style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w800),
                ),
              ),
            SizedBox(
              height: 20,
              child: SliderTheme(
                data: SliderTheme.of(context).copyWith(
                  trackHeight: dragging ? 4 : 2,
                  thumbShape: RoundSliderThumbShape(enabledThumbRadius: dragging ? 7 : 4),
                  overlayShape: const RoundSliderOverlayShape(overlayRadius: 12),
                  activeTrackColor: Colors.white,
                  inactiveTrackColor: Colors.white24,
                  thumbColor: Colors.white,
                  trackShape: const RectangularSliderTrackShape(),
                  padding: EdgeInsets.zero,
                ),
                child: Slider(
                  value: current,
                  max: max,
                  onChangeStart: (v) => setState(() => _dragValue = v),
                  onChanged: (v) => setState(() => _dragValue = v),
                  onChangeEnd: (v) {
                    widget.controller.seekTo(Duration(milliseconds: v.toInt()));
                    setState(() => _dragValue = null);
                  },
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  String _fmt(Duration d) {
    final m = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final s = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$m:$s';
  }
}

/// Burst of hearts played where the user double-tapped.
class HeartBurst extends StatelessWidget {
  final Offset position;

  const HeartBurst({super.key, required this.position});

  @override
  Widget build(BuildContext context) {
    return Positioned(
      left: position.dx - 50,
      top: position.dy - 50,
      child: IgnorePointer(
        child: TweenAnimationBuilder<double>(
          tween: Tween(begin: 0, end: 1),
          duration: const Duration(milliseconds: 750),
          builder: (context, t, _) {
            final scale = t < 0.3 ? 0.6 + t * 2 : 1.2 - (t - 0.3) * 0.3;
            return Opacity(
              opacity: t < 0.7 ? 1 : (1 - t) / 0.3,
              child: Transform.translate(
                offset: Offset(0, -40 * t),
                child: Transform.scale(
                  scale: scale,
                  child: const Icon(Icons.favorite_rounded, color: AppTheme.primary, size: 100),
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}
