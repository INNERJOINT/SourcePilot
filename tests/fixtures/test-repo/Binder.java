package android.os;

public class Binder implements IBinder {
    private static final String TAG = "Binder";

    public Binder() {}

    public boolean transact(int code, Parcel data, Parcel reply, int flags) {
        return onTransact(code, data, reply, flags);
    }

    protected boolean onTransact(int code, Parcel data, Parcel reply, int flags) {
        return false;
    }

    public String getInterfaceDescriptor() {
        return null;
    }

    public boolean pingBinder() {
        return true;
    }
}
