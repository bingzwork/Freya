# Development avatar

`current_avatar.vrm` is the temporary development mannequin. It is VRoid `AvatarSample_A.vrm`, sourced from [madjin/vrm-samples](https://github.com/madjin/vrm-samples).

The official usage conditions are published by VRoid at <https://vroid.pixiv.help/hc/en-us/articles/4402394424089>. They permit use in for-profit and non-profit activities and permit redistribution, but prohibit redistributing the sample VRM for a fee and prohibit representing it as a CC0 asset. Review the upstream conditions before any commercial distribution or asset replacement.

To replace the mannequin, overwrite `current_avatar.vrm` with a user-owned VRM or pass a configured model path with `--avatar-model`. The controller and UI do not depend on the model’s filename beyond the configured path. See `docs/AVATAR.md` for expected expressions, gaze behavior, and fallback rules.
