defmodule TestRepo.Utils do
  @moduledoc """
  Utility functions for TestRepo.
  """

  @doc """
  Converts a string to uppercase.

  ## Examples

      iex> TestRepo.Utils.upcase("hello")
      "HELLO"

  """
  def upcase(string) when is_binary(string) do
    String.upcase(string)
  end

  @doc """
  Calculates the factorial of a number.

  ## Examples

      iex> TestRepo.Utils.factorial(5)
      120

  """
  def factorial(0), do: 1
  def factorial(n) when n > 0 do
    n * factorial(n - 1)
  end

  @doc """
  Checks if a number is even.

  ## Examples

      iex> TestRepo.Utils.even?(4)
      true

      iex> TestRepo.Utils.even?(3)
      false

  """
  def even?(n) when is_integer(n) do
    rem(n, 2) == 0
  end
end 