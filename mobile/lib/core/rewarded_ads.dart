import 'dart:async';
import 'package:google_mobile_ads/google_mobile_ads.dart';
import 'constants.dart';

enum AdOutcome {
  /// The user watched the ad to the end.
  rewarded,

  /// The user closed the ad before the reward.
  dismissed,

  /// No ad could be loaded or shown (no fill, offline...): let the user continue.
  unavailable,
}

/// Loads and shows one rewarded video ad.
class RewardedAds {
  static bool _initialized = false;

  static Future<void> initialize() async {
    if (_initialized) return;
    _initialized = true;
    try {
      await MobileAds.instance.initialize();
    } catch (_) {}
  }

  static Future<AdOutcome> show(String unitId) async {
    await initialize();
    final ad = await _load(unitId.isNotEmpty ? unitId : AppConstants.testRewardedUnitId);
    if (ad == null) return AdOutcome.unavailable;

    final result = Completer<AdOutcome>();
    var rewarded = false;
    ad.fullScreenContentCallback = FullScreenContentCallback<RewardedAd>(
      onAdDismissedFullScreenContent: (ad) {
        ad.dispose();
        if (!result.isCompleted) result.complete(rewarded ? AdOutcome.rewarded : AdOutcome.dismissed);
      },
      onAdFailedToShowFullScreenContent: (ad, error) {
        ad.dispose();
        if (!result.isCompleted) result.complete(AdOutcome.unavailable);
      },
    );
    await ad.show(onUserEarnedReward: (_, _) => rewarded = true);
    return result.future;
  }

  static Future<RewardedAd?> _load(String unitId) {
    final completer = Completer<RewardedAd?>();
    RewardedAd.load(
      adUnitId: unitId,
      request: const AdRequest(),
      rewardedAdLoadCallback: RewardedAdLoadCallback(
        onAdLoaded: (ad) => completer.complete(ad),
        onAdFailedToLoad: (_) => completer.complete(null),
      ),
    );
    return completer.future.timeout(const Duration(seconds: 15), onTimeout: () => null);
  }
}
