import base64
import json
from modules.accounts.tokens import TokenGen
import pyotp
import requests

from django.shortcuts import get_object_or_404

from modules.accounts.models import User
from modules.accounts.serializers import (
    GoogleSocialLoginSerializer,
    LoginSerializer,
    RegisterSerializer,
    RequestPasswordResetPhoneSerializer,
    SetNewPasswordSerializer,
    TokenRequestSerializer,
)

from rest_framework import generics, serializers, status
from rest_framework.decorators import permission_classes

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class LoginViewSet(ModelViewSet, TokenObtainPairView):
    """
    Users can login with their phone number and password.
    """

    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class RegisterViewSet(ModelViewSet, TokenObtainPairView):
    """
    Endpoint allows Book Readers to register,
    using phone number, email, full_name, password, and user_type.
    Upon registration, a token is generated and sent to the user's phone number.
    """

    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    http_method_names = [
        "post",
    ]

    def create(self, request, *args, **kwargs):
        context = {
            "request": request,
        }
        serializer = self.get_serializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        # Check user existance
        if User.objects.filter(phone=request.data["phone"]).exists():
            userObject = User.objects.get(phone=request.data["phone"])
            userObject.counter += 1
            userObject.save()
            keygen = TokenGen()
            key = base64.b32encode(
                keygen.generate_token(
                    userObject.email,
                    userObject.phone,
                    userObject.timestamp,
                ).encode()
            )
            OTP = pyotp.HOTP(key)
            send_otp = OTP.at(userObject.counter)
            # Send OTP to user
            print("OTP:::", send_otp)

        res = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }
        return Response(
            {
                "user": serializer.data,
                "refresh": res["refresh"],
                "token": res["access"],
            },
            status=status.HTTP_201_CREATED,
        )


class RefreshViewSet(ModelViewSet, TokenRefreshView):
    """
    Endpoint allows users to refresh their token,
    by passing the refresh token in order to get a new access token
    """

    permission_classes = (AllowAny,)
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])

        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class AccountActivationViewSet(ModelViewSet):
    """
    After user registration, user will receive an OTP to activate
    their account, using this endpoint
    """

    serializer_class = TokenRequestSerializer
    permission_classes = [
        AllowAny,
    ]
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.get(phone=request.data["phone"])
            keygen = TokenGen()
            key = base64.b32encode(
                keygen.generate_token(user.email, user.phone, user.timestamp).encode(),
            )
            OTP = pyotp.HOTP(key)
            if OTP.verify(request.data["token"], user.counter):
                user.is_active = True
                user.save()
                return Response(
                    {"message": "Account activated successfully"},
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {"message": "Invalid OTP"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except User.DoesNotExist:
            return Response(
                {"error": "User does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )


# Request Phone for Password Reset
class RequestPasswordResetPhoneNumber(ModelViewSet):
    """
    User can request for password reset using phone number,
    where OTP will be sent to the user.
    """

    serializer_class = RequestPasswordResetPhoneSerializer
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # Check if user exists
            if User.objects.filter(phone=request.data["phone"]).exists():
                user = User.objects.get(phone=request.data["phone"])
                user.counter += 1
                user.save()
                keygen = TokenGen()
                key = base64.b32encode(
                    keygen.generate_token(
                        user.email,
                        user.phone,
                        user.timestamp,
                    ).encode()
                )
                OTP = pyotp.HOTP(key)
                send_otp = OTP.at(user.counter)
                # Send sms to user with a token
                if user.is_active:
                    # Send sms to user with the otp
                    print("Password Reset OTP: ", send_otp)
                    return Response(
                        {"message": "OTP sent successfully"},
                        status=status.HTTP_200_OK,
                    )
            return Response(
                {"error": "User with this phone number does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except User.DoesNotExist:
            return Response(
                {"error": "User with this phone number does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )


# Password Reset Token Check
class PasswordResetTokenCheckViewSet(ModelViewSet):
    """
    User enters the token sent to their phone number, if the token is valid,
    the user is redirected to the password reset page.
    Return phone and OTP
    """

    serializer_class = TokenRequestSerializer
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            if User.objects.filter(phone=request.data["phone"]).exists():
                user = User.objects.get(phone=request.data["phone"])
                keygen = TokenGen()
                key = base64.b32encode(
                    keygen.generate_token(
                        user.email,
                        user.phone,
                        user.timestamp,
                    ).encode()
                )
                OTP = pyotp.HOTP(key)
                if OTP.verify(request.data["token"], user.counter):
                    return Response(
                        {"message": "OTP verified successfully"},
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {"error": "Invalid OTP"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {"error": "User with this phone number does not exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except User.DoesNotExist:
            return Response(
                {"error": "User with this phone number does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )


# If the above OTP is verified, the user can reset their password
class SetNewPasswordViewSet(ModelViewSet):
    """
    The user can set a new password, if the OTP is verified successfully.
    Return password, password_confirm, phone and the verified token
    """

    serializer_class = SetNewPasswordSerializer
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            if User.objects.filter(phone=request.data["phone"]).exists():
                user = User.objects.get(phone=request.data["phone"])
                keygen = TokenGen()
                key = base64.b32encode(
                    keygen.generate_token(
                        user.email,
                        user.phone,
                        user.timestamp,
                    ).encode()
                )
                OTP = pyotp.HOTP(key)
                if OTP.verify(request.data["token"], user.counter):
                    password = request.data["password"]
                    password_confirm = request.data["password_confirm"]
                    if password and password_confirm and password != password_confirm:
                        raise serializers.ValidationError(
                            {"error": "Passwords do not match"}
                        )
                    else:
                        user.set_password(password)
                        user.save()
                        return Response(
                            {"message": "password reset successful"},
                            status=status.HTTP_200_OK,
                        )
                else:
                    return Response(
                        {"error": "Invalid OTP"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {"error": "User with this phone number does not exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except User.DoesNotExist:
            return Response(
                {"error": "User with this phone number does not exist"},
                status=status.HTTP_400_BAD_REQUEST,
            )


# Google Login
# https://www.googleapis.com/auth/userinfo.email
# https://developers.google.com/oauthplayground/
class GoogleSocialLogin(ModelViewSet):
    """
    Google Social Login, Use the url below to test the endpoint;
    https://www.googleapis.com/auth/userinfo.email
    https://developers.google.com/oauthplayground/
    return access_token from the url above
    """

    serializer_class = GoogleSocialLoginSerializer
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    def create(self, request, *args, **kwargs):
        payload = {
            "access_token": request.data.get("token"),
        }
        r = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo", params=payload
        )
        data = json.loads(r.text)
        print(data)
        if "error" in data:
            return Response(
                {"error": "Invalid or expired token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check user if does not exists
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            user = User.objects.create(
                email=data["email"],
                full_name="",
                phone=data["id"],
                is_active=True,
                role="Reader",
            )
            pic = data["picture"]
            password = User.objects.make_random_password()
            user.set_password(password)
            user.save()
        token = RefreshToken.for_user(user)
        return Response(
            {
                "refresh": str(token),
                "access": str(token.access_token),
            },
            status=status.HTTP_200_OK,
        )
