package android.app;

import android.os.Bundle;

public class Activity {
    private boolean mFinished;

    protected void onCreate(Bundle savedInstanceState) {}

    protected void onStart() {}

    protected void onResume() {}

    protected void onPause() {}

    protected void onStop() {}

    protected void onDestroy() {}

    public void finish() {
        mFinished = true;
    }

    public boolean isFinishing() {
        return mFinished;
    }
}
