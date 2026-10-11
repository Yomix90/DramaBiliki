import 'package:flutter/material.dart';
import '../core/app_theme.dart';
import '../core/constants.dart';

/// Episode grid split into ranges (1-30, 31-60...), highlighting the current
/// episode and dimming the ones already watched.
class EpisodeGrid extends StatefulWidget {
  final int total;
  final int? current;
  final Set<int> watched;
  final ValueChanged<int> onSelect;
  final bool shrinkWrap;

  const EpisodeGrid({
    super.key,
    required this.total,
    required this.onSelect,
    this.current,
    this.watched = const {},
    this.shrinkWrap = false,
  });

  @override
  State<EpisodeGrid> createState() => _EpisodeGridState();
}

class _EpisodeGridState extends State<EpisodeGrid> {
  late int _range;

  int get _rangeCount => (widget.total / AppConstants.episodesPerRange).ceil();

  @override
  void initState() {
    super.initState();
    final cur = widget.current ?? 1;
    _range = ((cur - 1) ~/ AppConstants.episodesPerRange).clamp(0, _rangeCount > 0 ? _rangeCount - 1 : 0);
  }

  @override
  Widget build(BuildContext context) {
    final start = _range * AppConstants.episodesPerRange + 1;
    final end = (start + AppConstants.episodesPerRange - 1).clamp(1, widget.total);
    final count = widget.total == 0 ? 0 : end - start + 1;

    return Column(
      mainAxisSize: widget.shrinkWrap ? MainAxisSize.min : MainAxisSize.max,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_rangeCount > 1)
          SizedBox(
            height: 34,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: _rangeCount,
              separatorBuilder: (_, _) => const SizedBox(width: 18),
              itemBuilder: (context, i) {
                final s = i * AppConstants.episodesPerRange + 1;
                final e = (s + AppConstants.episodesPerRange - 1).clamp(1, widget.total);
                final selected = i == _range;
                return GestureDetector(
                  onTap: () => setState(() => _range = i),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        '$s-$e',
                        style: TextStyle(
                          color: selected ? Colors.white : AppTheme.textMuted,
                          fontWeight: selected ? FontWeight.w800 : FontWeight.w500,
                          fontSize: 14,
                        ),
                      ),
                      const SizedBox(height: 4),
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 200),
                        width: selected ? 18 : 0,
                        height: 3,
                        decoration: BoxDecoration(
                          gradient: AppTheme.primaryGradient,
                          borderRadius: BorderRadius.circular(2),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        if (_rangeCount > 1) const SizedBox(height: 10),
        _wrapGrid(
          GridView.builder(
            shrinkWrap: widget.shrinkWrap,
            physics: widget.shrinkWrap ? const NeverScrollableScrollPhysics() : null,
            padding: const EdgeInsets.only(bottom: 16),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 6,
              crossAxisSpacing: 8,
              mainAxisSpacing: 8,
              childAspectRatio: 1,
            ),
            itemCount: count,
            itemBuilder: (context, idx) => _buildCell(start + idx),
          ),
        ),
      ],
    );
  }

  Widget _wrapGrid(Widget grid) => widget.shrinkWrap ? grid : Expanded(child: grid);

  Widget _buildCell(int ep) {
    final isCurrent = ep == widget.current;
    final isWatched = widget.watched.contains(ep);

    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => widget.onSelect(ep),
      child: Container(
        decoration: BoxDecoration(
          gradient: isCurrent ? AppTheme.primaryGradient : null,
          color: isCurrent ? null : AppTheme.surfaceLight,
          borderRadius: BorderRadius.circular(8),
        ),
        alignment: Alignment.center,
        child: isCurrent
            ? const Icon(Icons.graphic_eq_rounded, color: Colors.white, size: 20)
            : Text(
                '$ep',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 15,
                  color: isWatched ? AppTheme.textMuted : Colors.white,
                ),
              ),
      ),
    );
  }
}

/// Opens the episode selector as a bottom sheet.
Future<void> showEpisodeSheet({
  required BuildContext context,
  required String title,
  required int total,
  required ValueChanged<int> onSelect,
  int? current,
  Set<int> watched = const {},
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (sheetContext) {
      return SizedBox(
        height: MediaQuery.sizeOf(sheetContext).height * 0.6,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: Colors.white),
              ),
              const SizedBox(height: 12),
              Expanded(
                child: EpisodeGrid(
                  total: total,
                  current: current,
                  watched: watched,
                  onSelect: (ep) {
                    Navigator.pop(sheetContext);
                    onSelect(ep);
                  },
                ),
              ),
            ],
          ),
        ),
      );
    },
  );
}
